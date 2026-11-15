import pandas as pd

from claimguard.monitoring import drift, psi, run_health


def test_psi_and_drift():
    a = pd.Series(["x"] * 50 + ["y"] * 50)
    assert psi(a, a) < 1e-9 and psi(a, pd.Series(["x"] * 95 + ["y"] * 5)) > 0.25
    d = drift()
    assert d["rows"]["current"] == 2730 and d["label_shift"]["current_overturn_rate"] == 0.7234


def test_run_health():
    runs = [{"latency_s": 40, "cost": {"cost_usd": 0.003}, "status": "awaiting_human_signoff", "check_status": {"a": "PASS"}},
            {"latency_s": 50, "cost": {"cost_usd": 0.001}, "status": "not_finalized", "check_status": {"a": "FAIL"}}]
    h = run_health(runs)
    assert h["runs"] == 2 and h["check_pass_rate"]["a"] == 0.5 and h["cost_usd"]["total"] == 0.004
