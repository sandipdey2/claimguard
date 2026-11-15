from claimguard.models import FEATURES, get_model
from claimguard.text_model import classify_request, get_text_model


def test_time_split_and_no_leaky_features():
    r = get_model().report
    assert r["split"]["test"] == "2025" and "Findings" not in FEATURES and "DaysToReview" not in FEATURES and "ReportYear" not in FEATURES
    assert r["data"]["test"] == 2730


def test_metrics_reported_honestly():
    r = get_model().report
    t = r["test_metrics"]
    assert 0.70 < t["roc_auc"] < 0.80          # real, modest signal (not a leak)
    assert t["roc_auc"] > r["baselines_on_test"]["treatment_subcategory_rate"]["roc_auc"]
    assert 0 < t["brier"] < 0.25 and len(r["calibration_curve_test"]["mean_predicted"]) == 10


def test_predict_in_unit_interval():
    m = get_model()
    p = m.predict({"TreatmentCategory": "Pharmacy", "Type": "Medical Necessity"})
    assert 0 <= p <= 1 and m.band(p) in {"above_typical", "typical", "below_typical"}


def test_text_model_request_only():
    _, rep = get_text_model()
    assert 0.65 < rep["request_text"]["test"]["roc_auc"] < 0.85
    out = classify_request("authorization and coverage for an insulin pump")
    assert 0 <= out["overturn_probability_text"] <= 1 and out["top_terms"]
