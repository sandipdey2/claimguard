"""Train and report the P3 overturn model, the P4 text model (with the Findings leakage upper bound) and the P2 tests.

    python scripts/train_models.py           # writes eval/model_report.json, eval/text_model_report.json, eval/stats_results.json
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from claimguard import stats, text_model  # noqa: E402
from claimguard.models import get_model  # noqa: E402

EVAL = ROOT / "eval"


def main() -> None:
    EVAL.mkdir(exist_ok=True)
    t = time.time()
    m = get_model()
    (EVAL / "model_report.json").write_text(json.dumps(m.report, indent=1), encoding="utf-8")
    print("P3", m.report["selected"], m.report["test_metrics"], f"{time.time() - t:.1f}s")
    t = time.time()
    _, rep = text_model.train(include_leakage_check=True)
    (EVAL / "text_model_report.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print("P4 request-only test", rep["request_text"]["test"], "| leakage bound",
          rep["findings_full_text_leakage_upper_bound"].get("test", rep["findings_full_text_leakage_upper_bound"]), f"{time.time() - t:.1f}s")
    res = stats.all_tests()
    (EVAL / "stats_results.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    print("P2", len(res.get("tests", res)), "tests written")


if __name__ == "__main__":
    main()
