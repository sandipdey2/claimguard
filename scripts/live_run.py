"""Live end-to-end runs on real published CA DMHC IMR cases with gpt-4o-mini (Vocareum or Azure, CG_LLM_PROVIDER).

    python scripts/live_run.py MN25-45854 MN25-44606          # writes eval/logs/live_<ReferenceID>_<run_id>.json

The published Determination is held out from the agents and added to the log afterwards, for scoring only."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from claimguard.agents import run  # noqa: E402
from claimguard.cases import denial_from_imr  # noqa: E402
from claimguard.config import llm_available  # noqa: E402
from claimguard.runlog import build_log, save_log  # noqa: E402

REQUEST = "Draft an appeal letter and a denial-risk brief for this denied claim, citing Medicare coverage policy and published review decisions."


def one(ref: str) -> dict:
    d = denial_from_imr(ref)
    st = run(REQUEST, d["denial_text"], d["case"])
    log = build_log(st, ref, d["held_out"], d["denial_text"])
    path = save_log(log)
    print(json.dumps({"ref": ref, "status": log["status"], "latency_s": log["latency_s"], "cost_usd": log["cost"]["cost_usd"],
                      "llm_calls": log["cost"]["llm_calls"], "failed": log["failed"], "unrun": log["unrun"], "git_sha": log["receipt"]["git_sha"],
                      "receipt_verifies": log["receipt_verifies"], "log": str(path.relative_to(ROOT))}))
    return log


if __name__ == "__main__":
    if not llm_available():
        sys.exit("No LLM credentials (set OPENAI_API_KEY/OPENAI_API_BASE for Vocareum, or the AZURE_OPENAI_* settings with CG_LLM_PROVIDER=azure).")
    for ref in sys.argv[1:] or ["MN25-45854"]:
        one(ref)
