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


def test_red_team_rule1_absence_and_rule2_code_support():
    from claimguard.retrieval import get_index
    t = get_index().by_id["NCD-20.29:1"]["text"]
    real = " ".join(t.split()[:14])
    draft = (f'The NCD states "{real}" [NCD-20.29:1].\nThe NCD states "HBO is covered for every condition without limits" [NCD-20.29:1].\n'
             "There is no documentation provided about prior wound care.\nThe patient had three failed skin grafts last year.\n")
    r = T.confirm_red_team([{"rule": 2, "quote": f'The NCD states "{real}" [NCD-20.29:1].'},
                            {"rule": 2, "quote": 'The NCD states "HBO is covered for every condition without limits" [NCD-20.29:1].'},
                            {"rule": 1, "quote": "There is no documentation provided about prior wound care."},
                            {"rule": 1, "quote": "The patient had three failed skin grafts last year."}], draft)
    kept = " ".join(r["issues"])
    assert r["dropped_unverifiable"] == 2 and "every condition" in kept and "skin grafts" in kept
    assert T.citation_unsupported("See [NCD-999.9:1].") and not T.citation_unsupported("no citation here")


def test_red_team_rule1_policy_restatement_and_case_framing_regression():
    """Live Azure runs 6624778b / 072c6c63 (MN25-45854, short default API request) ended not_finalized because the red team's
    rule-1 issues on cited policy criteria and on case-fact framing were confirmed. Those are dropped now; invented patient facts
    are still confirmed, including ones that borrow policy wording or a policy citation."""
    s1 = ("However, continuous subcutaneous insulin infusion (CSII) and related drugs/supplies are covered as medically reasonable and "
          "necessary in the home setting for the treatment of diabetic patients who: (1) either meet the updated fasting C-Peptide testing "
          "requirement, or, are beta cell autoantibody positive; and, (2) satisfy the remaining criteria for insulin pump therapy as "
          "described below [NCD-280.14:2].")
    s2 = ("Additionally, the patient must have completed a comprehensive diabetes education program and have been on a program of multiple "
          "daily injections of insulin, with frequent self-adjustments of insulin doses for at least 6 months prior to initiation of the "
          "insulin pump [NCD-280.14:3].")
    s3 = "This appeal is based on the medical necessity of the requested device for effective diabetes management."
    bad = ["The patient has completed a comprehensive diabetes education program and has been on multiple daily injections of insulin [NCD-280.14:3].",
           "Patients must have been on multiple daily injections of insulin for at least 12 months prior to initiation of the insulin pump [NCD-280.14:3].",
           "She has had frequent severe hypoglycemia despite multiple daily injections.",
           "Details on the patient's diabetes management history support the appeal.",
           "Her HbA1c was 9.2% at the last visit."]
    case = {"intake": {"service": "authorization and coverage for a Tandem Mobi external ambulatory insulin pump", "denial_basis": "medical_necessity",
                       "treatment_category": "Pharmacy",
                       "case_facts": ["The health plan denied a request for authorization and coverage for a Tandem Mobi external ambulatory insulin pump.",
                                      "Denial type: Medical Necessity.", "Diagnosis category: Endocrine/Metabolic / Diabetes.",
                                      "Treatment category: Pharmacy / Insulin Pump.", "Age range: 11 to 20.", "Gender: Female."],
                       "missing_information": ["Details on the patient's diabetes management history"]},
            "case": {"ReferenceID": "MN25-45854", "DiagnosisSubCategory": "Diabetes", "TreatmentSubCategory": "Insulin Pump"}}
    draft = "\n\n".join([s3, s1, s2, *bad])
    # quotes as the reviewer gave them: s1 without its citation, truncated like the live issue
    r = T.confirm_red_team([{"rule": 1, "quote": s1[:160]}, {"rule": 1, "quote": s2}, {"rule": 1, "quote": s3}]
                           + [{"rule": 1, "quote": b} for b in bad], draft, case)
    kept = " ".join(r["issues"])
    assert r["verdict"] == "fail" and r["dropped_unverifiable"] == 3 and len(r["issues"]) == len(bad)
    for b in bad:
        assert b[:40] in kept
    assert "CSII" not in kept and "medical necessity of the requested device" not in kept
    # without the case facts, the framing sentence is not dropped (nothing to ground it on)
    r2 = T.confirm_red_team([{"rule": 1, "quote": s3}], draft)
    assert r2["verdict"] == "fail"
    # only the published facts count: the intake's missing_information is not grounding
    assert not T.restates_case_facts(bad[3], T._case_text(case))
