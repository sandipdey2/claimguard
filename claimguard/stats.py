"""Project 2 lineage: hypothesis tests on real published review outcomes, with effect sizes.

All tests are descriptive and non-causal: a difference in overturn rates between categories, years or states can come
from case mix, plan mix, reviewer organisations or what people choose to appeal. A p-value is context for the brief;
it never tells anyone they will win an appeal.
"""
from __future__ import annotations

import math
from functools import lru_cache
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats as st

from .data import load_dfs, load_imr

ALPHA = 0.05


def _p(p: float) -> float | str:
    """p-values below double precision are reported as a string instead of a misleading 0.0."""
    return "<1e-300" if p < 1e-300 else float(f"{p:.3g}")


def cramers_v(table: np.ndarray) -> float:
    chi2 = st.chi2_contingency(table, correction=False)[0]
    n = table.sum()
    r, k = table.shape
    return float(math.sqrt(chi2 / (n * (min(r, k) - 1)))) if n and min(r, k) > 1 else 0.0


def cohens_h(p1: float, p2: float) -> float:
    return float(2 * math.asin(math.sqrt(p1)) - 2 * math.asin(math.sqrt(p2)))


def two_proportion(x1: int, n1: int, x2: int, n2: int) -> dict:
    p1, p2 = x1 / n1, x2 / n2
    p = (x1 + x2) / (n1 + n2)
    se0 = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    z = (p1 - p2) / se0
    se = math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    return {"p1": round(p1, 4), "p2": round(p2, 4), "n1": n1, "n2": n2, "difference": round(p1 - p2, 4),
            "ci95": [round(p1 - p2 - 1.96 * se, 4), round(p1 - p2 + 1.96 * se, 4)], "z": round(z, 3),
            "p_value": _p(2 * st.norm.sf(abs(z))), "cohens_h": round(cohens_h(p1, p2), 3)}


def _chi(df: pd.DataFrame, col: str, label: str = "overturned", top: int | None = None) -> dict:
    d = df
    if top:
        keep = d[col].value_counts().head(top).index
        d = d[d[col].isin(keep)]
    tab = pd.crosstab(d[col], d[label])
    chi2, p, dof, _ = st.chi2_contingency(tab.to_numpy())
    rates = (d.groupby(col)[label].agg(["mean", "count"]).sort_values("mean", ascending=False))
    return {"test": "chi-square test of independence", "variable": col, "categories": int(len(tab)), "n": int(tab.to_numpy().sum()),
            "chi2": round(float(chi2), 2), "dof": int(dof), "p_value": _p(p), "cramers_v": round(cramers_v(tab.to_numpy()), 3),
            "rates": [{"category": str(i), "overturn_rate": round(float(r["mean"]), 4), "n": int(r["count"])} for i, r in rates.iterrows()]}


def _trend(df: pd.DataFrame, years: tuple[int, int]) -> dict:
    d = df[(df.ReportYear >= years[0]) & (df.ReportYear <= years[1])]
    g = d.groupby("ReportYear").overturned.agg(["sum", "count"])
    x = g.index.to_numpy(dtype=float)
    p_hat = (g["sum"] / g["count"]).to_numpy()
    # Cochran-Armitage test for trend in proportions
    n, s = g["count"].to_numpy(dtype=float), g["sum"].to_numpy(dtype=float)
    N, S = n.sum(), s.sum()
    pbar = S / N
    t_stat = float(np.sum(x * (s - n * pbar)))
    var = pbar * (1 - pbar) * (np.sum(n * x ** 2) - np.sum(n * x) ** 2 / N)
    z = t_stat / math.sqrt(var)
    return {"test": "Cochran-Armitage trend test (overturn rate by year)", "years": list(years), "n": int(N), "z": round(z, 2),
            "p_value": _p(2 * st.norm.sf(abs(z))),
            "rate_first_year": round(float(p_hat[0]), 4), "rate_last_year": round(float(p_hat[-1]), 4),
            "by_year": [{"year": int(a), "overturn_rate": round(float(b), 4), "n": int(c)} for a, b, c in zip(x, p_hat, n)]}


@lru_cache(maxsize=1)
def all_tests() -> dict:
    imr = load_imr()
    imr_c = imr[imr.ReportYear <= 2025]                 # 2026 is an incomplete year
    dfs = load_dfs()
    out: dict = {"scope": "CA DMHC IMR 2001-2025 (2026 incomplete, excluded); NY DFS external appeals 2019-2025 unless stated", "alpha": ALPHA}
    out["imr_by_treatment_category"] = _chi(imr_c, "TreatmentCategory", top=12)
    out["imr_by_review_type"] = _chi(imr_c, "Type")
    out["imr_trend_2015_2025"] = _trend(imr_c, (2015, 2025))
    ca = imr_c[(imr_c.ReportYear >= 2019) & (imr_c.ReportYear <= 2025)]
    ny = dfs[(dfs.decision_year >= 2019) & (dfs.decision_year <= 2025)]
    out["ca_vs_ny_2019_2025"] = {
        "test": "two-proportion z-test (overturn rate, CA IMR vs NY DFS external appeal)",
        "ny_counts_partial_as_overturned": two_proportion(int(ca.overturned.sum()), len(ca), int(ny.overturned_any.sum()), len(ny)),
        "ny_full_overturns_only": two_proportion(int(ca.overturned.sum()), len(ca), int(ny.overturned_full.sum()), len(ny)),
        "note": "Different laws, plan mix and reviewer organisations; descriptive comparison only."}
    exp = imr_c[imr_c.Type.isin(["Medical Necessity", "Experimental/Investigational"])]
    mn, ei = exp[exp.Type == "Medical Necessity"], exp[exp.Type == "Experimental/Investigational"]
    out["imr_medical_necessity_vs_experimental"] = {"test": "two-proportion z-test", **two_proportion(int(mn.overturned.sum()), len(mn),
                                                                                                         int(ei.overturned.sum()), len(ei)),
                                                    "group1": "Medical Necessity", "group2": "Experimental/Investigational"}
    out["dfs_by_denial_reason"] = _chi(ny.rename(columns={"overturned_any": "overturned"}), "denial_reason")
    out["dfs_by_coverage_type"] = _chi(ny.rename(columns={"overturned_any": "overturned"}), "coverage_type", top=8)
    n_tests = 7
    out["multiple_testing"] = {"tests": n_tests, "bonferroni_alpha": round(ALPHA / n_tests, 5),
                               "note": "with tens of thousands of rows tiny effects are 'significant'; read the effect sizes"}
    return out


def cohort_stats(treatment_category: str | None = None, review_type: str | None = None, diagnosis_category: str | None = None,
                 before_year: int | None = None) -> dict:
    """Descriptive overturn rate of published IMRs matching the filters (complete years only, optionally before a year)."""
    d = load_imr()
    d = d[d.ReportYear <= 2025]
    filt: dict[str, Any] = {}
    if before_year:
        d = d[d.ReportYear < int(before_year)]
        filt["before_year"] = int(before_year)
    for col, val in (("TreatmentCategory", treatment_category), ("Type", review_type), ("DiagnosisCategory", diagnosis_category)):
        if val:
            d = d[d[col] == val]
            filt[col] = val
    n = int(len(d))
    if n == 0:
        return {"filters": filt, "n": 0, "headline": "No published IMRs match these filters."}
    k = int(d.overturned.sum())
    lo, hi = st.binomtest(k, n).proportion_ci(0.95, method="wilson")
    recent = d[d.ReportYear >= d.ReportYear.max() - 2]
    return {"filters": filt, "n": n, "overturned": k, "overturn_rate": round(k / n, 4), "overturn_percent": round(100 * k / n, 1),
            "wilson_ci95": [round(float(lo), 4), round(float(hi), 4)], "years": [int(d.ReportYear.min()), int(d.ReportYear.max())],
            "last_3_years": {"n": int(len(recent)), "overturn_percent": round(100 * float(recent.overturned.mean()), 1) if len(recent) else None},
            "headline": f"{k} of {n} published IMRs ({_describe(filt)}) overturned the plan ({round(100 * k / n, 1)}%).",
            "caveat": "descriptive rate of past published reviews; not a prediction for any one case"}


def _describe(filt: dict) -> str:
    parts = [f"{k} = {v}" for k, v in filt.items() if k != "before_year"]
    if "before_year" in filt:
        parts.append(f"decided before {filt['before_year']}")
    return ", ".join(parts) or "all complete years"
