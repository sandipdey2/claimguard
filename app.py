"""ClaimGuard Streamlit app.   streamlit run app.py

Runs the LangGraph agents live (gpt-4o-mini via Vocareum or Azure OpenAI) when credentials are configured; otherwise it
opens the saved live-run logs in eval/logs so every tab still shows real outputs. Not legal or medical advice."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
try:  # Streamlit Community Cloud / local secrets.toml -> environment (values are never displayed)
    for _k, _v in st.secrets.items():
        if isinstance(_v, str | int | float) and _k.isupper():
            os.environ.setdefault(_k, str(_v))
except Exception:
    pass

from claimguard import __version__  # noqa: E402
from claimguard.cases import DEMO_CASES, denial_from_imr  # noqa: E402
from claimguard.config import LOGS, azure_flags, llm_available, load_contract, provider  # noqa: E402
from claimguard.harness import human_signoff, verify_receipt  # noqa: E402
from claimguard.prompts import DISCLAIMER  # noqa: E402

st.set_page_config(page_title="ClaimGuard", page_icon="🛡️", layout="wide")
EVAL = ROOT / "eval"
BADGE = {"awaiting_human_signoff": ("🟡", "Awaiting human sign-off"), "released": ("🟢", "Released by a human reviewer"),
         "rejected_by_human": ("⚪", "Rejected by the human reviewer"), "not_finalized": ("🔴", "Not finalized: a required check failed"),
         "blocked_unrun": ("🔴", "Blocked: a required check did not run"), "refused": ("⛔", "Refused before any LLM call")}


def jload(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def saved_logs() -> list[Path]:
    return sorted(LOGS.glob("live_*.json"), key=lambda p: p.stat().st_mtime, reverse=True) + sorted((LOGS / "dev").glob("live_*.json"))


# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.title("🛡️ ClaimGuard")
    st.caption(f"v{__version__} · cited appeal drafts + denial-risk briefs from public CMS policy and published IMR decisions")
    live = llm_available()
    st.markdown(f"**LLM:** gpt-4o-mini via `{provider()}` · {'connected' if live else 'no credentials (saved runs only)'}")
    flags = azure_flags()
    st.markdown("**Azure adapters:** " + ", ".join(f"{k} {'✅' if v else '—'}" for k, v in flags.items()))
    st.divider()
    mode = st.radio("Source", ["Saved live run", "Run a published case live"] + (["Paste a de-identified denial"] if live else []), index=0)
    if mode == "Saved live run":
        logs = saved_logs()
        if logs:
            pick = st.selectbox("Live-run log", logs, format_func=lambda p: f"{'dev/' if p.parent.name == 'dev' else ''}{p.stem}")
            if st.button("Open", type="primary") or "log" not in st.session_state:
                st.session_state.log = jload(pick)
                st.session_state.log_file = str(pick.relative_to(ROOT))
        else:
            st.info("No saved runs yet: run scripts/live_run.py.")
    else:
        if mode == "Run a published case live":
            ref = st.selectbox("Published CA DMHC IMR case (outcome held out)", [c["reference_id"] for c in DEMO_CASES],
                               format_func=lambda r: f"{r} · {next(c['why'] for c in DEMO_CASES if c['reference_id'] == r)}")
            d = denial_from_imr(ref)
            st.text_area("Denial text given to the agents", d["denial_text"], height=160, disabled=True)
            denial, case = d["denial_text"], d["case"]
        else:
            ref, case, d = None, None, {"held_out": None}
            denial = st.text_area("De-identified denial text (no names, IDs, dates of birth)", height=160)
        request = st.text_input("Request", "Draft an appeal letter and a denial-risk brief for this denied claim.")
        if st.button("Run agents", type="primary", disabled=not live or not denial.strip()):
            from claimguard.agents import run
            from claimguard.runlog import build_log
            with st.spinner("Planner → retriever → criteria → risk (MCP) → writer → red team → gate ..."):
                s = run(request, denial, case)
            st.session_state.log = build_log(s, ref, d.get("held_out"), denial)
            st.session_state.log_file = "(this session)"
        if not live:
            st.warning("Add OPENAI_API_KEY + OPENAI_API_BASE (Vocareum) or AZURE_OPENAI_* with CG_LLM_PROVIDER=azure to run live.")
    st.divider()
    st.caption(DISCLAIMER)

log: dict = st.session_state.get("log", {})
tabs = st.tabs(["Appeal draft", "Evidence & citations", "Risk model", "Stats", "Checks & receipt", "Monitoring", "Coverage matrix", "About"])

# ------------------------------------------------------------------ 1 appeal draft
with tabs[0]:
    if not log:
        st.info("Open a saved live run or run a case from the sidebar.")
    else:
        icon, text = BADGE.get(log.get("status", ""), ("❔", log.get("status")))
        st.subheader(f"{icon} {text}")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Latency", f"{log.get('latency_s')} s")
        c2.metric("Cost (list price)", f"${(log.get('cost') or {}).get('cost_usd', 0):.4f}")
        c3.metric("LLM calls", (log.get("cost") or {}).get("llm_calls"))
        c4.metric("Revisions", log.get("revisions"))
        st.caption(f"Source: {st.session_state.get('log_file')} · route: {' → '.join(log.get('route') or [])}")
        if log.get("status") == "refused":
            st.error(log.get("reason"))
        st.markdown(log.get("draft_md") or "_no draft_")
        st.download_button("Download draft (.md)", log.get("draft_md") or "", file_name="claimguard_appeal_draft.md")
        st.divider()
        st.markdown("### Human sign-off")
        rec = log.get("receipt") or {}
        if rec.get("status") != "awaiting_human_signoff":
            st.caption(f"Sign-off is only offered for drafts awaiting sign-off (this one is `{rec.get('status')}`).")
        elif not verify_receipt(rec):
            st.caption("This receipt was signed by another process key (set the same CG_RECEIPT_KEY to verify it); run a case live to sign off here.")
        else:
            with st.form("signoff"):
                reviewer = st.text_input("Reviewer name or role")
                note = st.text_input("Note (optional)")
                ok = st.checkbox("I reviewed the draft, its citations and the denial-risk brief")
                a, b = st.columns(2)
                approve, reject = a.form_submit_button("Approve and release"), b.form_submit_button("Reject")
            if approve or reject:
                if approve and not ok:
                    st.error("Tick the review box before approving.")
                else:
                    try:
                        log["receipt"] = human_signoff(rec, reviewer, bool(approve), note)
                        log["status"] = log["receipt"]["status"]
                        st.success(f"Status: {log['status']} (receipt re-signed)")
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
        if log.get("held_out_outcome"):
            with st.expander("Published outcome (held out from the agents; shown for evaluation only)"):
                st.json(log["held_out_outcome"])

# ------------------------------------------------------------------ 2 evidence
with tabs[1]:
    if log:
        gi = log.get("gate_inputs") or {}
        det = log.get("details") or {}
        st.markdown(f"**Citations in the draft:** {', '.join(det.get('citations') or []) or 'none'}")
        if det.get("unknown_citations") or det.get("citations_not_retrieved") or det.get("bad_quotes"):
            st.error({k: det.get(k) for k in ("unknown_citations", "citations_not_retrieved", "bad_quotes")})
        st.markdown("#### Policy excerpts selected by the retriever (CMS NCD)")
        for s in log.get("policy_selected") or []:
            txt = (gi.get("retrieved") or {}).get(s["chunk_id"], "")
            with st.expander(f"[{s['chunk_id']}] {s.get('relevance', '')}"):
                st.write(txt or "(text not stored in this log)")
                nid = s["chunk_id"].split(":")[0].replace("NCD-", "")
                st.caption(f"CMS Medicare Coverage Database, NCD {nid}")
        st.markdown("#### Verbatim quotes the writer used")
        st.table(pd.DataFrame(gi.get("quotes") or []))
        st.markdown("#### Published precedents (CA DMHC IMR, decided before the case year)")
        rows = log.get("precedent_rows") or [{"reference_id": r} for r in log.get("precedents") or []]
        st.dataframe(pd.DataFrame(rows), use_container_width=True)
        if log.get("criteria"):
            st.markdown("#### Coverage criteria to document")
            st.dataframe(pd.DataFrame((log["criteria"] or {}).get("criteria", [])), use_container_width=True)

# ------------------------------------------------------------------ 3 risk model
with tabs[2]:
    mr, tr = jload(EVAL / "model_report.json"), jload(EVAL / "text_model_report.json")
    if log.get("risk"):
        r = log["risk"]
        st.metric("Overturn-model signal for this case's categories", f"{r.get('overturn_percent')}%", help=r.get("limit"))
        sig = (log.get("signals") or {})
        if sig.get("text_model"):
            st.caption(f"Text model (request sentence only): {round(100 * sig['text_model']['overturn_probability_text'], 1)}%")
        if sig.get("cohort"):
            st.caption(sig["cohort"].get("headline"))
    if mr:
        st.markdown(f"**P3 served model:** {mr['served_model']}  ·  split: train {mr['split']['train']}, validation {mr['split']['validation']}, test {mr['split']['test']}")
        t = mr["test_metrics"]
        cols = st.columns(5)
        for c, k in zip(cols, ["roc_auc", "pr_auc", "brier", "recall", "f1"], strict=True):
            c.metric(f"Test {k}", t[k])
        st.markdown("Validation comparison")
        st.table(pd.DataFrame({k: v["val"] for k, v in mr["comparison_on_validation"].items()}).T[["roc_auc", "pr_auc", "brier", "f1"]])
        st.markdown("Baselines on the 2025 test year")
        st.json(mr["baselines_on_test"])
        cal = mr["calibration_curve_test"]
        st.line_chart(pd.DataFrame({"observed": cal["observed_rate"], "ideal": cal["mean_predicted"]}, index=cal["mean_predicted"]))
        st.caption(f"Prior shift: train overturn rate {mr['data']['train_overturn_rate']} vs test {mr['data']['test_overturn_rate']}, so the "
                   "calibrated model under-predicts in 2025. " + mr["limits"])
    if tr:
        rq, lk = tr["request_text"], tr.get("findings_full_text_leakage_upper_bound", {})
        st.markdown(f"**P4 text model:** {tr['model']} · request sentence only · test ROC-AUC {rq['test']['roc_auc']}, F1 {rq['test']['f1']}")
        if "test" in lk:
            st.caption(f"Leakage upper bound (full Findings text, NOT served): test ROC-AUC {lk['test']['roc_auc']}. The Findings state the decision.")
        st.json(rq.get("top_terms", {}))

# ------------------------------------------------------------------ 4 stats
with tabs[3]:
    sr = jload(EVAL / "stats_results.json")
    if sr:
        st.caption(f"{sr['scope']} · alpha {sr['alpha']} · {sr['multiple_testing']['note']}")
        rows = []
        for k, v in sr.items():
            if not isinstance(v, dict) or "test" not in v:
                continue
            core = v.get("ny_counts_partial_as_overturned", v)
            rows.append({"analysis": k, "test": v["test"], "n": core.get("n") or (core.get("n1", 0) + core.get("n2", 0)),
                         "statistic": core.get("chi2") or core.get("z"), "p": str(core.get("p_value")),
                         "effect": f"V={core['cramers_v']}" if "cramers_v" in core else f"h={core.get('cohens_h')}" if "cohens_h" in core else "-"})
        st.dataframe(pd.DataFrame(rows), use_container_width=True)
        tr_ = sr["imr_trend_2015_2025"]
        st.markdown("CA DMHC IMR overturn rate by year")
        st.bar_chart(pd.DataFrame(tr_["by_year"]).set_index("year")["overturn_rate"])
        st.markdown("By treatment category")
        st.dataframe(pd.DataFrame(sr["imr_by_treatment_category"]["rates"]), use_container_width=True)
        st.caption(sr["ca_vs_ny_2019_2025"].get("note", ""))

# ------------------------------------------------------------------ 5 checks & receipt
with tabs[4]:
    if log:
        cs = log.get("check_status") or {}
        st.dataframe(pd.DataFrame([{"check": k, "status": v} for k, v in cs.items()]), use_container_width=True)
        if log.get("unrun"):
            st.error(f"NOT_RUN (blocks release): {log['unrun']}")
        rt = log.get("red_team") or {}
        st.markdown(f"**Red team:** LLM verdict `{rt.get('llm_verdict')}`, code-confirmed verdict `{rt.get('verdict')}`, "
                    f"unverifiable issues dropped: {rt.get('dropped_unverifiable')}")
        rec = log.get("receipt") or {}
        v = verify_receipt(rec) if rec else False
        st.markdown(f"**Receipt:** HMAC-SHA256 · key `{rec.get('key_id')}` · verifies in this process: {'✅' if v else '— (different key)'} · "
                    f"verified at run time: {log.get('receipt_verifies')}")
        st.markdown(f"git `{rec.get('git_sha')}` (dirty={rec.get('git_dirty')}) · contract sha256 `{str(rec.get('contract_sha256'))[:16]}…`")
        st.json(rec, expanded=False)

# ------------------------------------------------------------------ 6 monitoring
with tabs[5]:
    from claimguard.monitoring import drift, load_runs, run_health
    runs = load_runs()
    st.markdown("#### Live-run health (eval/logs, dev runs included)")
    st.json(run_health(runs))
    st.markdown("#### Data drift: model training years (≤2023) vs 2025")
    dr = drift()
    st.dataframe(pd.DataFrame(dr["psi"]).T, use_container_width=True)
    st.caption(f"Label shift: overturn rate {dr['label_shift']['reference_overturn_rate']} → {dr['label_shift']['current_overturn_rate']}. "
               "PSI > 0.25 = major shift. Retrain and recalibrate when a new year is published.")
    summ = jload(EVAL / "summary.json")
    if summ:
        st.markdown("#### Offline evaluation (scripts/run_eval.py)")
        st.json(summ, expanded=False)
    if log.get("spans"):
        st.markdown("#### This run's spans")
        st.dataframe(pd.DataFrame(log["spans"]), use_container_width=True)

# ------------------------------------------------------------------ 7 coverage matrix
with tabs[6]:
    cov = ROOT / "docs" / "COVERAGE.md"
    st.markdown(cov.read_text(encoding="utf-8") if cov.exists() else "docs/COVERAGE.md missing")

# ------------------------------------------------------------------ 8 about
with tabs[7]:
    st.markdown(f"""### ClaimGuard v{__version__}
Agentic RAG for health-insurance denials: a **cited appeal-letter draft** and a **denial-risk brief**, built from public CMS National
Coverage Determinations and published California DMHC Independent Medical Review decisions, checked by 12 code-enforced gates
and released only after a named human signs off.

**Stack:** LangChain + LangGraph agents · live MCP server (stdio and streamable HTTP) · gpt-4o-mini (Vocareum for development,
Azure OpenAI in Azure AI Foundry for deployment) · optional Azure AI Search, Blob Storage, Content Safety Prompt Shields, App Insights.

**Data:** CMS NCD (public domain), CA DMHC IMR (CC BY, data.ca.gov), NY DFS external appeals (public records). No synthetic data, no PHI.

**Contract:** `{load_contract()['contract_version']}` · {len(load_contract()['required_checks'])} required checks · human sign-off required.

> {DISCLAIMER}
""")
    st.image(str(ROOT / "docs" / "architecture.png"))
