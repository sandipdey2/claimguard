"""Live end-to-end runs on real published CA DMHC IMR cases with gpt-4o-mini (Vocareum or Azure, CG_LLM_PROVIDER).

    python scripts/live_run.py MN25-45854 MN25-44606          # writes eval/logs/live_<ReferenceID>_<run_id>.json

The published Determination is held out from the agents and added to the log afterwards, for scoring only."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from claimguard.agents import run  # noqa: E402
from claimguard.cases import denial_from_imr  # noqa: E402
from claimguard.config import LOGS, llm_available, provider  # noqa: E402
from claimguard.harness import verify_receipt  # noqa: E402

REQUEST = "Draft an appeal letter and a denial-risk brief for this denied claim, citing Medicare coverage policy and published review decisions."


def one(ref: str) -> dict:
    d = denial_from_imr(ref)
    t0 = time.time()
    st = run(REQUEST, d["denial_text"], d["case"])
    fin = st["final"]
    rec = fin["receipt"]
    log = {"kind": "live_e2e", "reference_id": ref, "provider": provider(), "model": "gpt-4o-mini", "status": fin["status"], "reason": fin["reason"],
           "latency_s": round(time.time() - t0, 2), "cost": st["ctx"]["cost"], "check_status": fin["verification"].get("check_status"),
           "failed": fin["verification"].get("failed"), "unrun": fin["verification"].get("unrun_checks"),
           "details": fin["verification"].get("details"), "receipt": rec, "receipt_verifies": verify_receipt(rec),
           "risk": st.get("risk"), "signals": st.get("signals"), "precedents": [p["reference_id"] for p in st.get("precedents", [])],
           "policy_selected": (st.get("policy") or {}).get("selected"), "route": st.get("route"), "revisions": st.get("revisions"),
           "red_team": st.get("red_team"), "draft_md": st.get("draft_md"), "intake": st.get("intake"), "plan": st.get("plan"),
           "trace": st.get("trace"), "held_out_outcome": d["held_out"], "denial_text": d["denial_text"]}
    LOGS.mkdir(parents=True, exist_ok=True)
    path = LOGS / f"live_{ref}_{st['ctx']['run_id'][:8]}.json"
    path.write_text(json.dumps(log, indent=1, default=str), encoding="utf-8")
    print(json.dumps({"ref": ref, "status": log["status"], "latency_s": log["latency_s"], "cost_usd": log["cost"]["cost_usd"],
                      "llm_calls": log["cost"]["llm_calls"], "failed": log["failed"], "unrun": log["unrun"], "log": str(path.relative_to(ROOT))}))
    return log


if __name__ == "__main__":
    if not llm_available():
        sys.exit("No LLM credentials (set OPENAI_API_KEY/OPENAI_API_BASE for Vocareum, or the AZURE_OPENAI_* settings with CG_LLM_PROVIDER=azure).")
    for ref in sys.argv[1:] or ["MN25-45854"]:
        one(ref)
