"""Gardener: mine recurring failure patterns from eval/logs and PROPOSE small, testable fixes (propose-only, never edits code).

    python scripts/garden.py            # deterministic patterns -> eval/garden_report.json
    python scripts/garden.py --llm      # also ask gpt-4o-mini for proposals (one call, uses the GARDEN_REVIEW prompt)
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from claimguard.config import LOGS, load_contract  # noqa: E402
from claimguard.monitoring import load_runs  # noqa: E402


def patterns(runs: list[dict], min_support: int) -> list[dict]:
    seen: dict[str, list[str]] = defaultdict(list)
    for r in runs:
        rid = r.get("receipt", {}).get("run_id", r.get("_file", "?"))
        for c in r.get("failed") or []:
            seen[f"check_failed:{c}"].append(rid)
        for c in r.get("unrun") or []:
            seen[f"check_not_run:{c}"].append(rid)
        for t in r.get("trace") or []:
            if t.get("type") == "verify" and t.get("failed"):
                for c in t["failed"]:
                    seen[f"verifier_failed:{c}"].append(rid)
        for i in (r.get("red_team") or {}).get("issues", []):
            rule = i.get("rule") if isinstance(i, dict) else str(i).split(":")[0].replace("rule ", "")
            seen[f"red_team_confirmed_rule:{rule}"].append(rid)
        for i in (r.get("red_team") or {}).get("dropped", []):
            seen[f"red_team_dropped_rule:{str(i).split(':')[0].replace('rule ', '')}"].append(rid)
        if (r.get("red_team") or {}).get("dropped_unverifiable"):
            seen["red_team_unverifiable_quotes"].append(rid)
        if r.get("revisions"):
            seen["needed_revision"].append(rid)
    return [{"pattern": k, "support": len(v), "runs": sorted(set(v))[:10]} for k, v in sorted(seen.items(), key=lambda x: -len(x[1])) if len(v) >= min_support]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true")
    a = ap.parse_args()
    c = load_contract()
    runs = load_runs(LOGS)
    pats = patterns(runs, c["gardening"]["min_support"])
    report = {"runs_scanned": len(runs), "status_counts": dict(Counter(r.get("status") for r in runs)), "patterns": pats, "mode": "propose_only",
              "proposals": None}
    if a.llm and pats:
        from claimguard.config import get_llm
        from claimguard.prompts import GARDEN_REVIEW
        msg = get_llm().invoke(GARDEN_REVIEW.format(patterns_json=json.dumps(pats, indent=1), required_checks_json=json.dumps(c["required_checks"])))
        report["proposals"] = msg.content
    out = ROOT / "eval" / "garden_report.json"
    out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("runs_scanned", "status_counts")}), f"{len(pats)} patterns -> {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
