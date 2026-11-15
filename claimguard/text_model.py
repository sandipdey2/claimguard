"""Project 4 lineage: text classification of IMR text with TF-IDF + logistic regression (the shipped scorer).

Two honest variants, same time split as models.py (train <= 2023, validate 2024, test 2025; Findings text exists in the
committed snapshot for 2023+ only, so the full-text variant is trained on the raw CSV when it is present):
* ``request``  - only the pre-decision request sentence ("has requested authorization and coverage for ..."). Usable
                 before a decision; this is what the agents call (classify_request_text).
* ``findings`` - the full published Findings. It contains the reviewer's conclusion, so its score is a LEAKAGE UPPER
                 BOUND that shows why post-decision text must never be a pre-decision feature. Reported, never served.
The sequence-model (LSTM) idea from P4 is described in notebooks/README.md as optional and is not in the live app.
"""
from __future__ import annotations

import os
import threading
from typing import Any

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from .config import RAW, RUNTIME
from .data import load_imr, manifest
from .models import TEST_YEAR, TRAIN_END, VAL_YEAR, metrics

VERSION = "v1"


def _pipe() -> Pipeline:
    return Pipeline([("tfidf", TfidfVectorizer(sublinear_tf=True, ngram_range=(1, 2), min_df=3, max_features=60000, stop_words="english")),
                     ("clf", LogisticRegression(max_iter=3000, C=2.0))])


def _fit_eval(df: pd.DataFrame, col: str) -> tuple[Pipeline, dict]:
    df = df[df[col].fillna("").str.len() > 0]
    tr, va, te = df[df.ReportYear <= TRAIN_END], df[df.ReportYear == VAL_YEAR], df[df.ReportYear == TEST_YEAR]
    m = _pipe().fit(tr[col], tr.overturned)
    val = metrics(va.overturned.to_numpy(), m.predict_proba(va[col])[:, 1])
    m2 = _pipe().fit(pd.concat([tr, va])[col], pd.concat([tr, va]).overturned)
    test = metrics(te.overturned.to_numpy(), m2.predict_proba(te[col])[:, 1])
    return m2, {"rows": {"train": int(len(tr)), "validation": int(len(va)), "test": int(len(te))}, "validation": val, "test": test}


def top_terms(m: Pipeline, n: int = 12) -> dict:
    names = np.array(m.named_steps["tfidf"].get_feature_names_out())
    coef = m.named_steps["clf"].coef_.ravel()
    o = np.argsort(coef)
    return {"toward_overturned": names[o[-n:]][::-1].tolist(), "toward_upheld": names[o[:n]].tolist()}


def train(include_leakage_check: bool = False) -> tuple[Pipeline, dict]:
    df = load_imr()
    served, req = _fit_eval(df, "request_text")
    report: dict[str, Any] = {"request_text": {**req, "top_terms": top_terms(served), "use": "served (pre-decision request sentence only)"}}
    raw = RAW / "imr.csv"
    if not include_leakage_check:
        report["findings_full_text_leakage_upper_bound"] = {"status": "see eval/text_model_report.json (scripts/train_models.py)"}
    elif raw.exists():
        full = pd.read_csv(raw, usecols=["ReferenceID", "ReportYear", "Determination", "Findings"]).drop_duplicates()
        full["overturned"] = full.Determination.str.startswith("Overturned").astype(int)
        _, leak = _fit_eval(full, "Findings")
        report["findings_full_text_leakage_upper_bound"] = {**leak, "use": "NOT served: Findings state the decision, so this is leakage"}
    else:
        report["findings_full_text_leakage_upper_bound"] = {"status": "NOT_RUN", "reason": "data/raw/imr.csv absent (run scripts/fetch_data.py)"}
    report["split"] = {"train": f"<= {TRAIN_END}", "validation": VAL_YEAR, "test": TEST_YEAR}
    report["model"] = "TF-IDF (1-2 grams, sublinear, min_df=3) + logistic regression C=2.0"
    report["lstm"] = "optional P4 sequence-model note only (notebooks/README.md); not trained or served in v0.1"
    return served, report


_lock = threading.Lock()
_cached: tuple[Pipeline, dict] | None = None


def get_text_model() -> tuple[Pipeline, dict]:
    global _cached
    with _lock:
        if _cached is None:
            RUNTIME.mkdir(parents=True, exist_ok=True)
            sha = manifest()["snapshot_files"]["imr_slim.parquet"]["sha256"][:12]
            path = RUNTIME / f"text_model_{VERSION}_{sha}_{sklearn.__version__}.joblib"
            if path.exists():
                try:
                    _cached = joblib.load(path)
                except Exception:
                    _cached = None
            if _cached is None:
                _cached = train()
                tmp = path.with_suffix(f".{os.getpid()}.tmp")
                joblib.dump(_cached, tmp)
                os.replace(tmp, path)
        return _cached


def classify_request(text: str) -> dict:
    m, rep = get_text_model()
    p = float(m.predict_proba([text])[0, 1])
    vec, clf = m.named_steps["tfidf"], m.named_steps["clf"]
    x = vec.transform([text])
    contrib = x.multiply(clf.coef_.ravel()).toarray().ravel()
    names = vec.get_feature_names_out()
    idx = [i for i in np.argsort(-np.abs(contrib)) if contrib[i] != 0][:6]
    return {"overturn_probability_text": round(p, 4), "top_terms": [{"term": str(names[i]), "weight": round(float(contrib[i]), 3)} for i in idx],
            "test_roc_auc": rep["request_text"]["test"]["roc_auc"], "note": "TF-IDF + LR on the request sentence only; a signal, not a verdict"}
