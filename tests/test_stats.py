import math

from claimguard.stats import all_tests, cohens_h, cohort_stats, cramers_v, two_proportion


def test_two_proportion_math():
    r = two_proportion(60, 100, 40, 100)
    assert r["difference"] == 0.2 and abs(r["z"] - 2.828) < 0.01 and r["p_value"] < 0.01
    assert abs(r["cohens_h"] - cohens_h(0.6, 0.4)) < 1e-3 and r["ci95"][0] < 0.2 < r["ci95"][1]


def test_cramers_v_bounds():
    import numpy as np
    assert cramers_v(np.array([[50, 0], [0, 50]])) == 1.0
    assert math.isclose(cramers_v(np.array([[25, 25], [25, 25]])), 0.0, abs_tol=1e-9)


def test_all_tests_have_effect_sizes():
    t = all_tests()
    assert t["imr_by_treatment_category"]["cramers_v"] > 0 and t["imr_by_treatment_category"]["dof"] == 11
    ca_ny = t["ca_vs_ny_2019_2025"]["ny_counts_partial_as_overturned"]
    assert ca_ny["n1"] == 16128 and ca_ny["n2"] == 52894 and ca_ny["difference"] > 0
    assert t["imr_trend_2015_2025"]["z"] > 0


def test_cohort_stats_filters_and_ci():
    c = cohort_stats("Pharmacy", "Medical Necessity", before_year=2025)
    assert c["n"] > 1000 and c["years"][1] == 2024 and c["wilson_ci95"][0] < c["overturn_rate"] < c["wilson_ci95"][1]
    assert cohort_stats("No Such Category")["n"] == 0
