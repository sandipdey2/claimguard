"""Harness: run contract, budget accounting, the 12-check verifier (PASS / FAIL / NOT_RUN), the finalize gate and the
HMAC-signed receipt (git_sha, contract sha, feed versions, check statuses, human sign-off).

Adapted from NeuroGuard v2.6.1 (same PASS/FAIL/NOT_RUN semantics: a required check that never ran blocks the result
and is never a pass), rewritten for appeal letters: citations are NCD/LCD chunk ids and published IMR ReferenceIDs.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import subprocess
import time
import uuid
from dataclasses import dataclass, field

from .config import ROOT, load_contract, secret
from .guard import PHI, scan_injection

PASS, FAIL, NOT_RUN = "PASS", "FAIL", "NOT_RUN"
CITE = re.compile(r"\[((?:NCD|LCD)-[A-Z]?[\d.]+(?::\d+)?|IMR-[A-Z]{2}\d{2}-\d+)\]")
DISCLAIMER_PATTERNS = [r"not legal advice", r"not medical advice", r"qualified human", r"review"]
AUTHORITY = [r"\bi am (your|the patient'?s?|a) (doctor|physician|attorney|lawyer|nurse)\b", r"\bas (your|the patient'?s) (doctor|physician|attorney|lawyer)\b",
             r"\b(on behalf of|signed by) (dr\.?|doctor|the physician|counsel|attorney)\b", r"(?<!not a )(?<!not )(?<!no )(?<!cannot )\bguarantee[sd]?\b", r"\bwill (definitely|certainly) be (overturned|approved)\b",
             r"\b(you|the patient) will win\b", r"\b100% (chance|certain)\b", r"\blegal advice:\s", r"\bthis constitutes (legal|medical) advice\b"]
CHECKLIST = {"requested_service": r"(?im)^\*\*requested service:\*\*\s*\S",
             "denial_basis": r"(?im)^\*\*denial basis:\*\*\s*\S",
             "policy_citation": r"\[(?:NCD|LCD)-",
             "precedent_or_gap": r"(\[IMR-[A-Z]{2}\d{2}-\d+\]|no close (published )?precedent)",
             "requested_action": r"(?im)^\*\*requested action:\*\*\s*\S",
             "reviewer_questions": r"(?im)^##\s*questions for the human reviewer"}


def sha(obj) -> str:
    data = obj if isinstance(obj, (bytes, str)) else json.dumps(obj, sort_keys=True, default=str)
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


def price(input_tokens: int, output_tokens: int, cached_tokens: int, pricing: dict) -> float:
    uncached = max(0, input_tokens - cached_tokens)
    return (uncached * pricing["input_per_1m"] + cached_tokens * pricing["cached_input_per_1m"] + output_tokens * pricing["output_per_1m"]) / 1_000_000


@dataclass
class RunContext:
    session_id: str = "local"
    contract: dict = field(default_factory=load_contract)
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    started: float = field(default_factory=time.time)
    llm_calls: int = 0
    tool_calls: int = 0
    tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    cost_usd: float = 0.0
    spans: list = field(default_factory=list)
    audit: list = field(default_factory=list)
    decisions: list = field(default_factory=list)

    def __post_init__(self) -> None:
        self.contract_sha256 = sha(self.contract)
        self.log("harness", "contract_loaded", sha256=self.contract_sha256, budget=self.contract["budget"])

    def log(self, actor: str, event: str, **kw) -> None:
        self.audit.append({"ts": round(time.time(), 3), "actor": actor, "event": event, **kw})

    def decide(self, actor: str, kind: str, chosen, rationale: str, **kw) -> None:
        self.decisions.append({"seq": len(self.decisions) + 1, "actor": actor, "kind": kind, "chosen": chosen, "rationale": rationale, **kw})

    def record_llm(self, agent: str, msg, start: float, end: float) -> None:
        self.llm_calls += 1
        usage = getattr(msg, "usage_metadata", None) or {}
        inp, out = int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))
        cached = int((usage.get("input_token_details") or {}).get("cache_read", 0) or 0)
        self.tokens += int(usage.get("total_tokens", inp + out))
        self.input_tokens += inp
        self.output_tokens += out
        self.cached_tokens += cached
        cost = price(inp, out, cached, self.contract["pricing"])
        self.cost_usd += cost
        self.spans.append({"name": f"llm.{agent}", "start": start, "end": end, "attrs": {"agent": agent, "model": self.contract["model"],
                                                                                         "input_tokens": inp, "output_tokens": out, "cost_usd": round(cost, 7)}})
        try:
            from .observability import emit_span
            emit_span(f"llm.{agent}", start, end, {"agent": agent, "gen_ai.request.model": self.contract["model"], "gen_ai.usage.input_tokens": inp,
                                                   "gen_ai.usage.output_tokens": out, "run_id": self.run_id})
        except Exception:
            pass

    def record_tool(self, agent: str, tool: str, start: float, end: float, ok: bool, args: dict | None = None) -> None:
        self.tool_calls += 1
        self.spans.append({"name": f"mcp.tools/call.{tool}", "start": start, "end": end, "attrs": {"agent": agent, "tool": tool, "ok": ok}})
        try:
            from .observability import emit_span
            emit_span(f"mcp.tools/call.{tool}", start, end, {"agent": agent, "mcp.tool": tool, "ok": ok, "run_id": self.run_id})
        except Exception:
            pass

    def budget_left(self) -> bool:
        b = self.contract["budget"]
        return (self.llm_calls < b["max_llm_calls"] and self.tokens < b["max_total_tokens"] and self.cost_usd < b["max_cost_usd"]
                and time.time() - self.started < b["wall_clock_timeout_s"])

    def within_budget(self) -> bool:
        b = self.contract["budget"]
        return (self.llm_calls <= b["max_llm_calls"] and self.tokens <= b["max_total_tokens"] and self.tool_calls <= b["max_tool_calls"]
                and self.cost_usd <= b["max_cost_usd"] and time.time() - self.started <= b["wall_clock_timeout_s"])

    def cost_summary(self) -> dict:
        p = self.contract["pricing"]
        return {"model": self.contract["model"], "llm_calls": self.llm_calls, "tool_calls": self.tool_calls, "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens, "cached_input_tokens": self.cached_tokens, "cost_usd": round(self.cost_usd, 6),
                "rates_usd_per_1m": {"input": p["input_per_1m"], "output": p["output_per_1m"]}, "pricing_source": p["source"]}


# ----------------------------------------------------------------------------- verifier
NUM = re.compile(r"(?<![A-Za-z\-:.\d])(\d+(?:\.\d+)?)(?![\d\]])")
POOL_NUM = re.compile(r"\d+(?:\.\d+)?")


def _strip_for_numbers(text: str) -> str:
    text = CITE.sub(" ", text)
    text = re.sub(r"\b(NCD|LCD|IMR)[- ]?[A-Z]{0,2}[\d.:-]+", " ", text)
    text = re.sub(r"\b[A-Z]{2}\d{2}-\d+\b", " ", text)
    text = re.sub(r"^\s*#+.*$", " ", text, flags=re.M)
    text = re.sub(r"^\s*\d+\.\s", " ", text, flags=re.M)
    return text


def numbers(text: str) -> list[float]:
    return [float(x) for x in NUM.findall(_strip_for_numbers(text))]


def _decimals(x: float) -> int:
    r = repr(float(x))
    return 0 if r.endswith(".0") else len(r.split(".")[1]) if "." in r and "e" not in r else 6


def grounded(x: float, pool: set[float]) -> bool:
    """A draft number is grounded when some source number (or it x100 / /100, for rates vs percents) ROUNDS to it at the
    precision the draft wrote. A draft that is more precise than its source (93.7 when the source says 94) is not grounded."""
    if x in pool:
        return True
    d = _decimals(x)
    for v in pool:
        for cand in (v, v * 100, v / 100):
            if abs(round(cand, d) - x) < 1e-9:
                return True
    return False


def norm(t: str) -> str:
    t = (t or "").replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"')
    return re.sub(r"[^a-z0-9%]+", " ", t.lower()).strip()


def section(md: str, title: str) -> str:
    m = re.search(rf"^##\s*{re.escape(title)}\s*$(.*?)(?=^##\s|\Z)", md, flags=re.M | re.S | re.I)
    return m.group(1) if m else ""


def check_statuses(checks: dict, not_run: set[str], names) -> dict[str, str]:
    return {c: NOT_RUN if (c in not_run or c not in checks) else (PASS if checks[c] else FAIL) for c in names}


def verify(draft_md: str, quotes: list[dict], risk: dict | None, risk_statement: str | None, retrieved: dict, known_ids: set[str],
           evidence_text: str, injection: dict | None, red_team: dict | None, ctx: RunContext, *, require_red_team: bool = True,
           stage: str = "final") -> dict:
    """12 required checks over the rendered draft.

    ``quotes`` = [{"citation_id", "quote"}] the writer claims are verbatim policy text; ``retrieved`` = id -> text of every
    chunk / precedent the tools returned this run; ``known_ids`` = every id in the corpus and the IMR table; ``evidence_text``
    = all tool payloads (the number pool); ``injection`` = input + document scan results; ``red_team`` = confirmed review.
    """
    checks: dict[str, bool] = {}
    not_run: set[str] = set()
    md = draft_md or ""
    has_text = bool(md.strip())
    low = md.lower()
    checks["disclaimer_present"] = all(re.search(p, low) for p in DISCLAIMER_PATTERNS)
    cited = sorted(set(CITE.findall(md)))
    def _known(c: str) -> bool:
        return c in known_ids or c.split(":")[0] in known_ids
    missing = [c for c in cited if not _known(c)]
    checks["citations_exist"] = bool(cited) and not missing
    not_retrieved = [c for c in cited if c not in retrieved and not any(r.startswith(c + ":") for r in retrieved)]
    checks["citations_retrieved"] = bool(cited) and not not_retrieved
    bad_quotes = []
    for q in quotes or []:
        src = retrieved.get(q.get("citation_id", ""), "")
        if not q.get("quote") or len(norm(q["quote"])) < 12 or norm(q["quote"]) not in norm(src):
            bad_quotes.append(q.get("citation_id"))
    if not quotes:
        not_run.add("quotes_verbatim")
    checks["quotes_verbatim"] = bool(quotes) and not bad_quotes
    pool = {float(x) for x in POOL_NUM.findall(evidence_text)} | {95.0, 100.0}
    nums = numbers(md)
    ungrounded = sorted({x for x in nums if not grounded(x, pool)})
    checks["numbers_grounded"] = not ungrounded
    pct = (risk or {}).get("overturn_percent")
    if risk is None or pct is None or risk_statement is None:
        not_run.add("risk_matches_model")
    checks["risk_matches_model"] = pct is not None and risk_statement is not None and f"{pct:.1f}%" in risk_statement and f"{pct:.1f}%" in md
    missing_items = [k for k, p in CHECKLIST.items() if not re.search(p, md, re.I)]
    checks["checklist_complete"] = not missing_items
    phi = [n for n, pat in PHI if re.search(pat, md)]
    checks["no_phi_in_output"] = not phi
    auth = [m.group(0) for p in AUTHORITY for m in [re.search(p, low)] if m]
    checks["no_authority_or_guarantee"] = not auth
    if injection is None:
        not_run.add("injection_scan_clean")
    out_inj = scan_injection(md)
    checks["injection_scan_clean"] = injection is not None and bool(injection.get("input_clean")) and bool(injection.get("documents_clean")) and not out_inj
    if red_team is None or not require_red_team:
        not_run.add("red_team_pass")
    checks["red_team_pass"] = bool(red_team) and (red_team or {}).get("verdict") == "pass"
    checks["within_budget"] = ctx.within_budget()
    if not has_text:
        not_run |= {"disclaimer_present", "citations_exist", "citations_retrieved", "numbers_grounded", "checklist_complete", "no_phi_in_output",
                    "no_authority_or_guarantee", "quotes_verbatim", "risk_matches_model"}
    for c in not_run:
        checks[c] = False
    contract_checks = list(ctx.contract["required_checks"])
    required = [c for c in contract_checks if require_red_team or c != "red_team_pass"]
    status = check_statuses(checks, not_run, list(dict.fromkeys(contract_checks + list(checks))))
    failed = [c for c in required if status[c] == FAIL]
    unrun = [c for c in required if status[c] == NOT_RUN]
    details = {"citations": cited, "unknown_citations": missing, "citations_not_retrieved": not_retrieved, "bad_quotes": bad_quotes,
               "ungrounded_numbers": ungrounded, "missing_checklist_items": missing_items, "phi_types": phi, "authority_or_guarantee": auth,
               "output_injection_patterns": [p[:40] for p in out_inj], "red_team_issues": (red_team or {}).get("issues", []), "stage": stage,
               "not_run": sorted(c for c, s in status.items() if s == NOT_RUN)}
    return {"checks": checks, "check_status": status, "failed": failed, "unrun_checks": unrun, "required": required,
            "passed": not failed and not unrun, "details": details}


def release_decision(v: dict) -> tuple[str, str | None]:
    """blocked_unrun (a required check never ran) > not_finalized (a check failed) > awaiting_human_signoff."""
    if v.get("unrun_checks"):
        return "blocked_unrun", "required check(s) not run: " + ", ".join(v["unrun_checks"])
    if v.get("failed"):
        return "not_finalized", "required check(s) failed: " + ", ".join(v["failed"])
    return "awaiting_human_signoff", None


def not_reviewed(ctx: RunContext) -> dict:
    req = list(ctx.contract["required_checks"])
    return {"checks": {c: False for c in req}, "check_status": {c: NOT_RUN for c in req}, "failed": [], "unrun_checks": req,
            "required": req, "passed": False, "details": {"not_run": req}}


# ----------------------------------------------------------------------------- receipt
_EPHEMERAL = os.urandom(32)


def git_revision() -> dict:
    """Commit the run executed (GIT_SHA env on hosts without .git, e.g. a container image built by CI)."""
    env_sha = os.environ.get("CG_GIT_SHA") or os.environ.get("GIT_SHA")
    try:
        s = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=3)
        if s.returncode == 0:
            d = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT, capture_output=True, text=True, timeout=3)
            return {"git_sha": s.stdout.strip(), "git_dirty": bool(d.stdout.strip())}
    except Exception:
        pass
    return {"git_sha": env_sha or "unknown", "git_dirty": None}


def _key() -> tuple[bytes, str]:
    k = secret("CG_RECEIPT_KEY")
    if k:
        return k.encode(), "CG_RECEIPT_KEY:" + hashlib.sha256(k.encode()).hexdigest()[:8]
    return _EPHEMERAL, "ephemeral:" + hashlib.sha256(_EPHEMERAL).hexdigest()[:8]


def sign_receipt(body: dict) -> dict:
    key, key_id = _key()
    body = {k: v for k, v in body.items() if k not in ("signature", "key_id", "algorithm", "signed_at")}
    body = {**body, "key_id": key_id, "algorithm": "HMAC-SHA256", "signed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    canon = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return {**body, "signature": hmac.new(key, canon.encode(), hashlib.sha256).hexdigest()}


def verify_receipt(receipt: dict) -> bool:
    key, key_id = _key()
    if receipt.get("key_id") != key_id:
        return False
    body = {k: v for k, v in receipt.items() if k != "signature"}
    canon = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return hmac.compare_digest(hmac.new(key, canon.encode(), hashlib.sha256).hexdigest(), receipt.get("signature", ""))


def human_signoff(receipt: dict, reviewer: str, approved: bool, note: str = "") -> dict:
    """Add the human decision to the receipt and re-sign it. Only a draft awaiting sign-off can be released."""
    if not verify_receipt(receipt):
        raise ValueError("receipt signature does not verify; refusing to add a sign-off")
    if receipt.get("status") != "awaiting_human_signoff":
        raise ValueError(f"status is {receipt.get('status')!r}; only 'awaiting_human_signoff' drafts can be signed off")
    reviewer = re.sub(r"[^A-Za-z .'-]", "", reviewer or "")[:80].strip()
    if not reviewer:
        raise ValueError("a reviewer name or role is required")
    signoff = {"reviewer": reviewer, "approved": bool(approved), "note": (note or "")[:300], "at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    status = "released" if approved else "rejected_by_human"
    checks = {**receipt.get("check_status", {}), "human_signoff": PASS if approved else FAIL}
    return sign_receipt({**receipt, "human_signoff": signoff, "status": status, "check_status": checks, "previous_signature": receipt["signature"]})
