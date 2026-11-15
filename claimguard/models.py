"""Project 3 lineage: predict whether a published CA DMHC IMR overturns the health plan's denial.

* Features known when a review is filed only: diagnosis and treatment (sub)categories, review Type (medical necessity /
  experimental-investigational / urgent care), IMR type (standard / expedited), age range and gender bands.
  Excluded on purpose: Findings text (written after the decision, it states the outcome), DaysToReview / DaysToAdopt
  (post-filing durations), and ReportYear (a time split must not extrapolate a year code).
* Time split: train 2001-2023, validate 2024, test 2025. 2026 is incomplete (546 rows) and is not used.
* Candidates: logistic regression (one-hot) and histogram gradient boosting; picked on validation ROC-AUC; served model
  refit on train+validation with sigmoid calibration; test metrics reported once.
* Baselines: majority class, and the historical (train-period) overturn rate of the treatment subcategory.
* The score is a signal for the brief, never a verdict and never used to decide whether to appeal.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.calibration import CalibratedClassifierCV, calibration_curve
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, confusion_matrix, f1_score, precision_score, recall_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, OrdinalEncoder

from .config import RUNTIME
from .data import load_imr, manifest

FEATURES = ["DiagnosisCategory", "DiagnosisSubCategory", "TreatmentCategory", "TreatmentSubCategory", "Type", "IMRType", "AgeRange", "PatientGender"]
TRAIN_END, VAL_YEAR, TEST_YEAR = 2023, 2024, 2025
MODEL_VERSION = "v1"
SEED = 42


def _lr() -> Pipeline:
    pre = ColumnTransformer([("cat", OneHotEncoder(handle_unknown="ignore", min_frequency=5), FEATURES)])
    return Pipeline([("pre", pre), ("clf", LogisticRegression(max_iter=3000, C=0.5))])


def _hgb() -> Pipeline:
    pre = ColumnTransformer([("cat", OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1, encoded_missing_value=-1, min_frequency=10, max_categories=250), FEATURES)])
    return Pipeline([("pre", pre), ("clf", HistGradientBoostingClassifier(categorical_features=list(range(len(FEATURES))), max_iter=300,
                                                                          learning_rate=0.05, max_leaf_nodes=31, l2_regularization=1.0,
                                                                          random_state=SEED))])


def metrics(y, p, thr: float = 0.5) -> dict:
    pred = (p >= thr).astype(int)
    tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
    return {"n": int(len(y)), "positives": int(y.sum()), "roc_auc": round(float(roc_auc_score(y, p)), 4),
            "pr_auc": round(float(average_precision_score(y, p)), 4), "brier": round(float(brier_score_loss(y, p)), 4),
            "threshold": round(float(thr), 3), "recall": round(float(recall_score(y, pred, zero_division=0)), 4),
            "precision": round(float(precision_score(y, pred, zero_division=0)), 4), "f1": round(float(f1_score(y, pred, zero_division=0)), 4),
            "accuracy": round(float((pred == y).mean()), 4), "confusion": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)}}


def split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    return df[df.ReportYear <= TRAIN_END], df[df.ReportYear == VAL_YEAR], df[df.ReportYear == TEST_YEAR]


def subcategory_rate_baseline(train: pd.DataFrame, target: pd.DataFrame, smooth: float = 20.0) -> np.ndarray:
    prior = train.overturned.mean()
    g = train.groupby("TreatmentSubCategory").overturned.agg(["sum", "count"])
    rate = (g["sum"] + smooth * prior) / (g["count"] + smooth)
    return target.TreatmentSubCategory.map(rate).fillna(prior).to_numpy()


@dataclass
class OverturnModel:
    served: CalibratedClassifierCV
    report: dict
    test_probs: list = field(default_factory=list, repr=False)

    def predict(self, case: dict) -> float:
        row = {f: str(case.get(f) or "Unknown") for f in FEATURES}
        return float(self.served.predict_proba(pd.DataFrame([row])[FEATURES])[0, 1])

    def band(self, p: float) -> str:
        base = self.report["data"]["train_overturn_rate"]
        if p >= base + 0.10:
            return "above_typical"
        if p <= base - 0.10:
            return "below_typical"
        return "typical"


def train() -> OverturnModel:
    df = load_imr()
    tr, va, te = split(df)
    ytr, yva, yte = tr.overturned.to_numpy(), va.overturned.to_numpy(), te.overturned.to_numpy()
    comparison = {}
    for name, make in {"logistic_regression": _lr, "hist_gradient_boosting": _hgb}.items():
        m = make().fit(tr[FEATURES], ytr)
        comparison[name] = {"val": metrics(yva, m.predict_proba(va[FEATURES])[:, 1])}
    best = max(comparison, key=lambda k: comparison[k]["val"]["roc_auc"])
    make = {"logistic_regression": _lr, "hist_gradient_boosting": _hgb}[best]
    trva = pd.concat([tr, va])
    served = CalibratedClassifierCV(make(), method="sigmoid", cv=5).fit(trva[FEATURES], trva.overturned.to_numpy())
    pte = served.predict_proba(te[FEATURES])[:, 1]
    test = metrics(yte, pte)
    base_sub = subcategory_rate_baseline(trva, te)
    maj = int(trva.overturned.mean() >= 0.5)
    baselines = {"majority_class": {"label": "overturned" if maj else "upheld", "accuracy": round(float((yte == maj).mean()), 4), "roc_auc": 0.5,
                                    "note": "always predicts the majority label of train+validation"},
                 "treatment_subcategory_rate": metrics(yte, base_sub)}
    frac, mean_pred = calibration_curve(yte, pte, n_bins=10, strategy="quantile")
    cat_counts = trva.TreatmentCategory.value_counts()
    report = {
        "task": "P(IMR overturns the health plan's denial) from pre-decision categorical fields",
        "features": FEATURES,
        "excluded_features": {"Findings": "post-decision text that states the outcome (leakage)", "DaysToReview/DaysToAdopt": "post-filing durations",
                              "ReportYear": "not extrapolated across a time split"},
        "split": {"train": f"ReportYear <= {TRAIN_END}", "validation": str(VAL_YEAR), "test": str(TEST_YEAR), "excluded": "2026 (incomplete year)"},
        "data": {"train": int(len(tr)), "validation": int(len(va)), "test": int(len(te)), "train_overturn_rate": round(float(ytr.mean()), 4),
                 "test_overturn_rate": round(float(yte.mean()), 4), "snapshot_sha256": manifest()["snapshot_files"]["imr_slim.parquet"]["sha256"]},
        "comparison_on_validation": comparison, "selected": best,
        "served_model": f"{best} + sigmoid calibration (CalibratedClassifierCV, cv=5), refit on train+validation",
        "test_metrics": test, "baselines_on_test": baselines,
        "calibration_curve_test": {"mean_predicted": [round(float(v), 4) for v in mean_pred], "observed_rate": [round(float(v), 4) for v in frac]},
        "treatment_categories_seen": {k: int(v) for k, v in cat_counts.items()},
        "sklearn": sklearn.__version__,
        "limits": "Association model on published review outcomes in California commercial plans. It does not know the clinical record, "
                  "is not a probability that a particular appeal will win, and must not be used to discourage anyone from appealing.",
    }
    return OverturnModel(served=served, report=report, test_probs=[[int(a), round(float(b), 5)] for a, b in zip(yte, pte)])


_lock = threading.Lock()
_model: OverturnModel | None = None


def get_model() -> OverturnModel:
    global _model
    with _lock:
        if _model is None:
            RUNTIME.mkdir(parents=True, exist_ok=True)
            sha = manifest()["snapshot_files"]["imr_slim.parquet"]["sha256"][:12]
            path = RUNTIME / f"overturn_model_{MODEL_VERSION}_{sha}_{sklearn.__version__}.joblib"
            if path.exists():
                try:
                    _model = joblib.load(path)
                except Exception:
                    _model = None
            if _model is None:
                _model = train()
                tmp = path.with_suffix(f".{os.getpid()}.tmp")
                joblib.dump(_model, tmp)
                os.replace(tmp, path)
        return _model
