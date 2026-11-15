"""One shape for a finished run, shared by scripts/live_run.py, the Streamlit app and the monitoring tab."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import LOGS, provider
from .harness import verify_receipt


def build_log(st: dict, reference_id: str | None = None, held_out: dict | None = None, denial_text: str = "") -> dict[str, Any]:
    fin = st["final"]
    ver = fin.get("verification") or {}
    rec = fin["receipt"]
    return {"kind": "live_e2e", "reference_id": reference_id, "provider": provider(), "model": "gpt-4o-mini", "status": fin["status"],
            "reason": fin.get("reason"), "latency_s": st["ctx"]["latency_s"], "cost": st["ctx"]["cost"], "check_status": ver.get("check_status"),
            "failed": ver.get("failed"), "unrun": ver.get("unrun_checks"), "details": ver.get("details"), "receipt": rec,
            "receipt_verifies": verify_receipt(rec), "risk": st.get("risk"), "signals": st.get("signals"),
            "precedents": [p["reference_id"] for p in st.get("precedents", [])], "precedent_rows": st.get("precedents", []),
            "policy_selected": (st.get("policy") or {}).get("selected"), "criteria": st.get("criteria"), "route": st.get("route"),
            "revisions": st.get("revisions"), "red_team": st.get("red_team"), "draft_md": st.get("draft_md"), "intake": st.get("intake"),
            "plan": st.get("plan"), "trace": st.get("trace"), "held_out_outcome": held_out, "denial_text": denial_text,
            "gate_inputs": st.get("gate_inputs"), "spans": st["ctx"].get("spans")}


def save_log(log: dict, logs_dir: Path = LOGS) -> Path:
    logs_dir.mkdir(parents=True, exist_ok=True)
    path = logs_dir / f"live_{log.get('reference_id') or 'custom'}_{log['receipt']['run_id'][:8]}.json"
    path.write_text(json.dumps(log, indent=1, default=str), encoding="utf-8")
    return path
