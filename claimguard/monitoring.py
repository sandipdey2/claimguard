"""Monitoring: run-log health (latency, cost, check pass rates) and data drift between the model's training years and the newest year."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

from .config import LOGS
from .data import load_imr


def load_runs(logs_dir: Path = LOGS, include_dev: bool = True) -> list[dict]:
    files = sorted(logs_dir.glob("live_*.json")) + (sorted((logs_dir / "dev").glob("live_*.json")) if include_dev else [])
    runs = []
    for f in files:
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        r["_file"] = str(f.relative_to(logs_dir.parent.parent)) if logs_dir.parent.parent in f.parents else f.name
        r["_dev"] = f.parent.name == "dev"
        runs.append(r)
    return runs


def run_health(runs: list[dict]) -> dict[str, Any]:
    if not runs:
        return {"runs": 0}
    lat = [r["latency_s"] for r in runs if r.get("latency_s") is not None]
    cost = [r["cost"]["cost_usd"] for r in runs if r.get("cost")]
    checks: dict[str, dict[str, int]] = {}
    for r in runs:
        for c, s in (r.get("check_status") or {}).items():
            checks.setdefault(c, {"PASS": 0, "FAIL": 0, "NOT_RUN": 0})[s] = checks.setdefault(c, {}).get(s, 0) + 1
    status = pd.Series([r.get("status") for r in runs]).value_counts().to_dict()
    return {"runs": len(runs), "status_counts": status, "latency_s": {"mean": round(sum(lat) / len(lat), 2), "max": max(lat)} if lat else None,
            "cost_usd": {"total": round(sum(cost), 6), "mean": round(sum(cost) / len(cost), 6)} if cost else None,
            "check_pass_rate": {c: round(v.get("PASS", 0) / max(1, sum(v.values())), 3) for c, v in checks.items()}}


def psi(expected: pd.Series, actual: pd.Series, eps: float = 1e-4) -> float:
    """Population stability index between two categorical distributions (>0.25 = major shift, 0.1-0.25 = moderate)."""
    cats = set(expected) | set(actual)
    e, a = expected.value_counts(normalize=True), actual.value_counts(normalize=True)
    return float(sum((a.get(c, 0) + eps - e.get(c, 0) - eps) * math.log((a.get(c, 0) + eps) / (e.get(c, 0) + eps)) for c in cats))


def drift(train_end: int = 2023, current: int = 2025) -> dict[str, Any]:
    df = load_imr()
    ref, cur = df[df.ReportYear <= train_end], df[df.ReportYear == current]
    out = {}
    for col in ("TreatmentCategory", "DiagnosisCategory", "Type", "AgeRange"):
        v = psi(ref[col].fillna("Unknown"), cur[col].fillna("Unknown"))
        out[col] = {"psi": round(v, 4), "level": "major" if v > 0.25 else "moderate" if v > 0.1 else "stable"}
    return {"reference": f"<= {train_end}", "current": current, "psi": out,
            "label_shift": {"reference_overturn_rate": round(float(ref.overturned.mean()), 4), "current_overturn_rate": round(float(cur.overturned.mean()), 4)},
            "rows": {"reference": int(len(ref)), "current": int(len(cur))}}
