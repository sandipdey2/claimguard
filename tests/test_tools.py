import json

from claimguard import tools as T
from claimguard.cases import DEMO_CASES, denial_from_imr, parse_denial
from claimguard.server_policy import ServerPolicy


def test_demo_cases_are_real_published_rows_and_hold_out_outcome():
    for c in DEMO_CASES:
        d = denial_from_imr(c["reference_id"])
        assert d["case"]["ReferenceID"] == c["reference_id"] and d["case"]["ReportYear"] == 2025
        assert "Overturned" not in d["denial_text"] and "Upheld" not in d["denial_text"]
        assert d["held_out"]["Determination"].endswith("Decision of Health Plan")


def test_get_imr_case_withholds_outcome():
    r = T.get_imr_case("MN25-45854")
    assert "Determination" not in r and "Findings" not in r and r["TreatmentSubCategory"] == "Insulin Pump"
    assert "error" in T.get_imr_case("XX00-0")


def test_parse_denial():
    p = parse_denial("The health plan denied a request for a cochlear implant. Denial type: Experimental/Investigational. NCD 50.3")
    assert p["service"].startswith("a cochlear implant") and p["denial_basis"] == "experimental_investigational" and p["ncd_mentions"] == ["50.3"]


def test_match_criteria_never_says_met():
    m = T.match_coverage_criteria(["NCD-280.14:3"], ["insulin pump", "diabetes education program", "multiple daily injections"])
    assert m["criteria"] and {c["status"] for c in m["criteria"]} <= {"related_case_fact", "needs_documentation"}
    assert T.match_coverage_criteria(["NOPE"], [])["unknown_chunk_ids"] == ["NOPE"]


def test_confirm_red_team_drops_hallucinated_and_disclaimer_quotes():
    from claimguard.prompts import DISCLAIMER
    draft = f"I am writing as the representative. The doctor guarantees approval.\n{DISCLAIMER}"
    r = T.confirm_red_team([{"rule": 4, "quote": "The doctor guarantees approval."}, {"rule": 1, "quote": "a sentence that is not in the draft"},
                            {"rule": 5, "quote": "ClaimGuard drafts are not legal advice and not medical advice."},
                            {"rule": 8, "quote": "I am writing as the representative."}], draft)
    assert r["verdict"] == "fail" and len(r["issues"]) == 1 and r["dropped_unverifiable"] == 3


def test_score_and_graph():
    s = T.score_overturn_likelihood("Endocrine/Metabolic", "Diabetes", "Pharmacy", "Insulin Pump", "Medical Necessity", "Standard")
    assert 0 <= s["overturn_probability"] <= 1 and s["overturn_percent"] == round(100 * s["overturn_probability"], 1)
    g = T.graph_neighbors("Insulin Pump", 3)
    assert g["edges"]["treatment->policy"][0]["doc_id"].startswith("NCD-")


def test_server_policy_refuses():
    p = ServerPolicy()
    f = p.guard("search_coverage_policy")(lambda **kw: "ok")
    assert "refused" in json.loads(f(query="x", k=50))["error"] and f(query="x", k=2) == "ok"
    g = p.guard("get_imr_case")(lambda **kw: "ok")
    assert "refused" in g(reference_id="MN25-45854", include_outcome=True) and len(p.refusals) == 2
