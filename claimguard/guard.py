"""Input and document guardrails: PHI redaction, prompt-injection detection, scope and refusal rules.

Deterministic scanner first (always on, so a free-tier exhaustion or an outage can never open the gate), then Azure AI
Content Safety Prompt Shields when AZURE_CONTENT_SAFETY_ENDPOINT is configured (user prompt + retrieved documents,
i.e. direct and indirect injection). The combined verdict is the stricter of the two.
"""
from __future__ import annotations

import re
from typing import Any

from .config import secret

INJECTION = [
    r"ignore (all |any |the )?(previous|prior|above|earlier|your) (instructions|rules|prompts?|guidelines)",
    r"disregard (your|the|all|any) (rules|instructions|guardrails|system prompt|disclaimer)",
    r"(reveal|print|show|repeat|output|leak) (your|the) (system prompt|hidden prompt|instructions|api key|secrets?|keys?)",
    r"\b(jailbreak|developer mode|dan mode|do anything now)\b",
    r"\byou are now (a|an|in|the) ",
    r"</?(system|assistant|tool|developer)>",
    r"(bypass|disable|turn off|skip|remove|omit|drop) (the )?(guardrails?|safety|filters?|verifier|disclaimer|red team|checks?)",
    r"(new|updated|override) (system )?instructions?:",
    r"(do not|don't|never) (include|add|mention) (the |a )?disclaimer",
    r"mark (all|every) (checks?|citations?) (as )?(pass|valid)",
    # v0.1 eval follow-up (patterns added after the first injection eval missed 4 of 16 prompts; see eval/README.md)
    r"\byou are now dan\b|\bact as an? (unfiltered|unrestricted|uncensored|jailbroken)\b",
    r"\b(override|forget|ignore) (your |the |all )?(safety )?(rules|guidelines|guardrails|instructions|prompts)\b",
    r"\b(invent|fabricate|make up) (any |fake |new )?(ncd |lcd |policy )?citations?\b",
]
PHI = [
    ("email", r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    ("ssn", r"\b\d{3}-\d{2}-\d{4}\b"),
    ("phone", r"(?<![\d-])(\+?1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?![\d-])"),
    ("mrn", r"\b(mrn|medical record( number)?|member id|subscriber id|patient id|policy number)[:#\s]*[A-Za-z0-9-]{4,}\b"),
    ("date_of_birth", r"\b(dob|date of birth|born on)[:\s]*\d{1,4}[/-]\d{1,2}[/-]\d{1,4}\b"),
    ("street_address", r"\b\d{1,5}\s+([A-Z][a-z]+\s){1,3}(Street|St|Avenue|Ave|Road|Rd|Lane|Ln|Drive|Dr|Boulevard|Blvd|Way|Court|Ct)\b"),
    ("person_name", r"\b(Mr|Mrs|Ms|Miss|Dr)\.?\s+[A-Z][a-z]+(\s[A-Z][a-z]+)?"),
    ("api_key", r"\b(sk|voc)-[A-Za-z0-9._-]{12,}"),
]
REFUSE = {
    "fabricate_record": r"\b(make up|invent|fabricate|create|generate|write)\b.{0,15}\b(fake|fictional|synthetic|made-up|fabricated)\b.{0,20}\b(patient|medical|clinical|records?|history)\b",
    "fabricate_patient": r"\b(make up|invent|fabricate|create|generate) (a |an |some )?(fake |fictional |synthetic )?(patient|medical history|clinical history|records?|diagnos\w*|test results?)\b",
    "impersonation": r"\b(sign|write|pretend|claim|say)\b.{0,40}\b(as|from|that you are|you're) (my |the |a )?(doctor|physician|attorney|lawyer|nurse|md)\b",
    "guarantee": r"\b(guarantee|promise|ensure|make sure)\b.{0,40}\b(win|overturn|approv\w*|succeed|success)",
    "file_on_behalf": r"\b(file|submit|send|fax|mail)\b.{0,20}\b(appeal|letter|claim)\b.{0,40}\b(on my behalf|for me)\b",
    "file_with_insurer": r"\b(file|submit|send|fax|mail|email)\b.{0,30}\b(the |my |this )?(appeal|letter|claim)\b.{0,30}\b(to|with) (the |my )?(insurer|insurance|plan|payer|medicare|cms)",
}
REFUSAL_TEXT = {
    "fabricate_patient": "ClaimGuard never invents patients, records or clinical history. Use a published public case or your own de-identified facts.",
    "impersonation": "ClaimGuard cannot write as a physician or attorney. Drafts are written for the patient or their representative and must be reviewed by a qualified human.",
    "guarantee": "No one can guarantee an appeal outcome. ClaimGuard reports public review statistics as context only.",
    "fabricate_record": "ClaimGuard never invents patients, records or clinical history. Use a published public case or your own de-identified facts.",
    "file_on_behalf": "ClaimGuard never files, submits, faxes or mails anything. It produces a draft for human review.",
    "file_with_insurer": "ClaimGuard never files, submits, faxes or mails anything. It produces a draft for human review.",
    "out_of_scope": "ClaimGuard only helps with health-insurance denials, coverage policy and appeal drafts.",
    "prompt_injection": "The request contains instructions that try to override ClaimGuard's rules, so it was stopped.",
    "phi": "The text looks like it contains personal identifiers. Remove names, member IDs, dates of birth and contact details, then try again.",
}
IN_SCOPE = (r"(deni\w*|appeal|claim|coverage|covered|insur\w*|plan|medicare|medicaid|prior auth\w*|authori[sz]\w*|imr|independent medical review|"
            r"external (review|appeal)|ncd|lcd|policy|medical(ly)? necess\w*|experimental|investigational|formulary|benefit|reimburs\w*|payer|"
            r"treatment|therapy|service|procedure|surgery|device|drug|medication|test|scan|imaging|letter|draft)")


def redact(text: str) -> tuple[str, list[str]]:
    found: list[str] = []
    out = text or ""
    for name, pat in PHI:
        flags = re.IGNORECASE if name in ("mrn", "date_of_birth") else 0
        out, n = re.subn(pat, f"[REDACTED-{name.upper()}]", out, flags=flags)
        found += [name] * n
    return out, found


def scan_injection(text: str) -> list[str]:
    low = (text or "").lower()
    return [p for p in INJECTION if re.search(p, low)]


def prompt_shields(user_prompt: str, documents: list[str]) -> dict:
    """Azure AI Content Safety Prompt Shields (text:shieldPrompt). Returns status NOT_CONFIGURED / ERROR / OK with flags."""
    endpoint = secret("AZURE_CONTENT_SAFETY_ENDPOINT")
    if not endpoint:
        return {"status": "NOT_CONFIGURED", "service": "azure_content_safety_prompt_shields"}
    try:
        import httpx
        key = secret("AZURE_CONTENT_SAFETY_KEY")
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Ocp-Apim-Subscription-Key"] = key
        else:
            from azure.identity import DefaultAzureCredential  # type: ignore[import-not-found]
            headers["Authorization"] = "Bearer " + DefaultAzureCredential().get_token("https://cognitiveservices.azure.com/.default").token
        body = {"userPrompt": user_prompt[:10000], "documents": [d[:10000] for d in documents[:5]]}
        r = httpx.post(f"{endpoint.rstrip('/')}/contentsafety/text:shieldPrompt?api-version=2024-09-01", headers=headers, json=body, timeout=10)
        r.raise_for_status()
        j = r.json()
        user_attack = bool((j.get("userPromptAnalysis") or {}).get("attackDetected"))
        doc_attack = any(d.get("attackDetected") for d in j.get("documentsAnalysis") or [])
        return {"status": "OK", "service": "azure_content_safety_prompt_shields", "user_attack": user_attack, "document_attack": doc_attack}
    except Exception as exc:
        return {"status": "ERROR", "service": "azure_content_safety_prompt_shields", "error": type(exc).__name__}


def check_input(request: str, denial_text: str = "") -> dict:
    """Run before any LLM call. Returns allowed + reason; PHI is redacted, and PHI in the denial text blocks the run."""
    q_red, q_found = redact(request)
    d_red, d_found = redact(denial_text)
    both = f"{q_red}\n{d_red}"
    base: dict[str, Any] = {"request": q_red, "denial_text": d_red, "phi_redacted": q_found + d_found}
    hits = scan_injection(both)
    shields = prompt_shields(q_red, [d_red] if d_red else [])
    base["prompt_shields"] = shields
    if hits or shields.get("user_attack") or shields.get("document_attack"):
        return {**base, "allowed": False, "reason": "prompt_injection", "detail": REFUSAL_TEXT["prompt_injection"], "patterns": [h[:50] for h in hits]}
    for reason, pat in REFUSE.items():
        if re.search(pat, both, re.I):
            return {**base, "allowed": False, "reason": reason, "detail": REFUSAL_TEXT[reason]}
    if [f for f in q_found + d_found if f != "person_name"] or len([f for f in q_found + d_found if f == "person_name"]) > 0:
        return {**base, "allowed": False, "reason": "phi", "detail": REFUSAL_TEXT["phi"]}
    if q_red.strip() and not re.search(IN_SCOPE, both.lower()):
        return {**base, "allowed": False, "reason": "out_of_scope", "detail": REFUSAL_TEXT["out_of_scope"]}
    return {**base, "allowed": True, "reason": "ok", "detail": "passed input guardrails"}


def scan_documents(docs: list[str]) -> dict:
    """Indirect-injection scan of retrieved policy / precedent text before it reaches the writer."""
    flagged = [i for i, d in enumerate(docs) if scan_injection(d)]
    shields = prompt_shields("Scan retrieved documents for embedded instructions.", docs) if docs else {"status": "NOT_RUN"}
    return {"scanned": len(docs), "flagged_local": flagged, "prompt_shields": shields,
            "clean": not flagged and not shields.get("document_attack")}
