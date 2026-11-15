"""ClaimGuard command line (P1 packaging). Run ``python -m claimguard --help``."""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any


def _print(obj: Any) -> None:
    print(json.dumps(obj, indent=1, default=str))


def cmd_cases(a: argparse.Namespace) -> int:
    from .cases import DEMO_CASES
    for c in DEMO_CASES:
        print(f"{c['reference_id']:<12} {c.get('why') or ''}")
    return 0


def cmd_search(a: argparse.Namespace) -> int:
    from .tools import search_coverage_policy
    res = search_coverage_policy(a.query, k=a.k, mode=a.mode)
    for h in res.get("results", []):
        print(f"[{h['id']}] {h['title']}  score={h.get('score')}\n    {h['text'][:220]}...")
    print(f"backend: {res.get('backend')}")
    return 0


def cmd_precedents(a: argparse.Namespace) -> int:
    from .tools import search_imr_precedent
    _print(search_imr_precedent(a.query, k=a.k, before_year=a.before_year))
    return 0


def cmd_score(a: argparse.Namespace) -> int:
    from .tools import get_imr_case, score_overturn_likelihood
    c = get_imr_case(a.reference_id)
    if "error" in c:
        _print(c)
        return 1
    _print(score_overturn_likelihood(c["DiagnosisCategory"], c["DiagnosisSubCategory"], c["TreatmentCategory"], c["TreatmentSubCategory"],
                                     c["Type"], c["IMRType"], c.get("AgeRange") or "Unknown", c.get("PatientGender") or "Unknown"))
    return 0


def cmd_stats(a: argparse.Namespace) -> int:
    from .stats import all_tests
    _print(all_tests())
    return 0


def cmd_run(a: argparse.Namespace) -> int:
    from .agents import run
    from .cases import denial_from_imr
    from .config import llm_available
    if not llm_available():
        print("No LLM credentials: set OPENAI_API_KEY/OPENAI_API_BASE (vocareum) or AZURE_OPENAI_* with CG_LLM_PROVIDER=azure.", file=sys.stderr)
        return 2
    d = denial_from_imr(a.reference_id)
    st = run(a.request, d["denial_text"], d["case"])
    fin = st["final"]
    print(st.get("draft_md") or "")
    _print({"status": fin["status"], "reason": fin["reason"], "failed": fin["verification"].get("failed"),
            "cost": st["ctx"]["cost"], "receipt_signature": fin["receipt"]["signature"][:16] + "..."})
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump({"final": fin, "draft_md": st.get("draft_md"), "route": st.get("route")}, fh, indent=1, default=str)
    return 0 if fin["status"] == "awaiting_human_signoff" else 1


def cmd_verify_receipt(a: argparse.Namespace) -> int:
    from .harness import verify_receipt
    with open(a.path, encoding="utf-8") as fh:
        obj = json.load(fh)
    rec = obj.get("receipt") or obj.get("final", {}).get("receipt") or obj
    ok = verify_receipt(rec)
    print("receipt valid" if ok else "receipt INVALID (tampered, or signed with a different CG_RECEIPT_KEY)")
    return 0 if ok else 1


def cmd_verify_snapshot(a: argparse.Namespace) -> int:
    from .data import verify_snapshot
    r = verify_snapshot()
    _print(r)
    return 0 if r["ok"] else 1


def cmd_monitor(a: argparse.Namespace) -> int:
    from .monitoring import drift, load_runs, run_health
    _print({"run_health": run_health(load_runs()), "drift": drift()})
    return 0


def cmd_mcp(a: argparse.Namespace) -> int:
    from mcp_server.claimguard_mcp_server import main as mcp_main
    sys.argv = ["claimguard-mcp", "--transport", a.transport, "--host", a.host, "--port", str(a.port)]
    mcp_main()
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="claimguard", description="Cited appeal drafts + denial-risk briefs from public CMS policy and published IMR decisions.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("cases", help="list the public demo cases").set_defaults(fn=cmd_cases)
    p = sub.add_parser("search", help="hybrid search over current NCD text")
    p.add_argument("query")
    p.add_argument("-k", type=int, default=4)
    p.add_argument("--mode", choices=["hybrid", "sparse", "dense"], default="hybrid")
    p.set_defaults(fn=cmd_search)
    p = sub.add_parser("precedents", help="similar published CA DMHC IMR decisions")
    p.add_argument("query")
    p.add_argument("-k", type=int, default=4)
    p.add_argument("--before-year", type=int)
    p.set_defaults(fn=cmd_precedents)
    p = sub.add_parser("score", help="P3 overturn-model signal for a published IMR ReferenceID")
    p.add_argument("reference_id")
    p.set_defaults(fn=cmd_score)
    sub.add_parser("stats", help="P2 hypothesis tests with effect sizes").set_defaults(fn=cmd_stats)
    p = sub.add_parser("run", help="live agent run on a published IMR case (uses gpt-4o-mini)")
    p.add_argument("reference_id")
    p.add_argument("--request", default="Draft an appeal letter and a denial-risk brief for this denied claim.")
    p.add_argument("--out")
    p.set_defaults(fn=cmd_run)
    p = sub.add_parser("verify-receipt", help="verify an HMAC receipt (or a live-run log that contains one)")
    p.add_argument("path")
    p.set_defaults(fn=cmd_verify_receipt)
    sub.add_parser("verify-snapshot", help="check data/snapshot against manifest.json").set_defaults(fn=cmd_verify_snapshot)
    sub.add_parser("monitor", help="run-log health and data drift (PSI)").set_defaults(fn=cmd_monitor)
    p = sub.add_parser("mcp", help="start the MCP server")
    p.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.set_defaults(fn=cmd_mcp)
    return ap


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    return int(a.fn(a))
