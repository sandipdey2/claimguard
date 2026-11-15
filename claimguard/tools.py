"""Pure tool functions behind the MCP server (also unit-tested directly). Every function returns JSON-serialisable data."""
from __future__ import annotations

import re

from .cases import parse_denial as _parse
from .data import dfs_case, feed_versions, imr_case, load_imr, load_ncd, manifest
from .guard import scan_documents as _scan
from .harness import norm
from .retrieval import get_index, get_precedents, search_policy, tokens

CRIT_SPLIT = re.compile(r"(?<=[.;:])\s+(?=[A-Z(])|\n+-\s*|\n{2,}")
CRITERIA_CUES = re.compile(r"\b(covered|coverage|must|required|requires|only if|criteria|indicat\w*|eligible|reasonable and necessary|"
                           r"not covered|nationally non-covered|documentation|conditions?|meets?|at least|prior to|failure of)\b", re.I)


def parse_denial(text: str) -> dict:
    return _parse(text)


def get_imr_case(reference_id: str, include_outcome: bool = False) -> dict:
    row = imr_case(reference_id)
    if row is None:
        return {"error": f"no published IMR with ReferenceID {reference_id!r}"}
    if not include_outcome:
        for k in ("Determination", "overturned", "Findings", "DaysToReview", "DaysToAdopt", "findings_chars"):
            row.pop(k, None)
        row["note"] = "outcome and reviewer Findings withheld (the agents must not see the decision of the case they are drafting for)"
    return row


def get_dfs_case(case_number: str) -> dict:
    return dfs_case(case_number) or {"error": f"no NY DFS external appeal with Case Number {case_number!r}"}


def search_coverage_policy(query: str, k: int = 4, mode: str = "hybrid") -> dict:
    res = search_policy(query[:300], k, mode)
    return {"backend": res["backend"], "results": [{"id": h["id"], "doc_id": h["doc_id"], "title": h["title"], "effective": h.get("effective"),
                                                     "url": h.get("url"), "score": h.get("score"), "text": h["text"]} for h in res["results"]]}


def get_ncd(ncd_id: str) -> dict:
    nid = ncd_id.replace("NCD-", "").replace("NCD", "").strip()
    d = load_ncd()
    hit = d[d.ncd_id == nid]
    if hit.empty:
        return {"error": f"no current NCD {nid!r}"}
    r = hit.iloc[0]
    chunks = [c["id"] for c in get_index().chunks if c["doc_id"] == f"NCD-{nid}"]
    return {"id": f"NCD-{nid}", "title": r.title, "version": int(r.version), "effective": r.effective, "url": r.url,
            "api_last_updated": r.api_last_updated, "chunk_ids": chunks, "item_service": (r.item_service or "")[:1500],
            "indications_limitations_preview": (r.indications_limitations or "")[:2500]}


def match_coverage_criteria(chunk_ids: list[str], facts: list[str]) -> dict:
    """Split cited policy excerpts into criterion sentences and mark whether any case fact mentions the same key terms.
    It never decides that a criterion is met (that needs the clinical record); it says what needs documentation."""
    ix = get_index()
    fact_toks = set(tokens(" ".join(facts)))
    out, unknown = [], []
    for cid in chunk_ids[:6]:
        c = ix.by_id.get(cid)
        if c is None:
            unknown.append(cid)
            continue
        for sent in CRIT_SPLIT.split(c["text"]):
            s = sent.strip(" -\n")
            if len(s) < 40 or not CRITERIA_CUES.search(s):
                continue
            overlap = sorted(set(tokens(s)) & fact_toks)
            out.append({"chunk_id": cid, "criterion": s[:400], "status": "related_case_fact" if len(overlap) >= 2 else "needs_documentation",
                        "overlap_terms": overlap[:8]})
            if len(out) >= 14:
                break
    return {"criteria": out, "unknown_chunk_ids": unknown,
            "rule": "related_case_fact = the case facts mention >= 2 of the criterion's key terms; this is NOT a determination that it is met"}


def search_imr_precedent(query: str, k: int = 4, before_year: int | None = None, exclude_id: str | None = None,
                         treatment_category: str | None = None) -> dict:
    hits = get_precedents().search(query[:300], max(1, min(int(k), 6)), before_year, exclude_id, treatment_category)
    return {"results": hits, "filters": {"before_year": before_year, "exclude_id": exclude_id, "treatment_category": treatment_category},
            "note": "published, de-identified CA DMHC IMR decisions; cite as [IMR-<reference_id>]"}


def score_overturn_likelihood(DiagnosisCategory: str, DiagnosisSubCategory: str, TreatmentCategory: str, TreatmentSubCategory: str,
                              Type: str, IMRType: str, AgeRange: str = "Unknown", PatientGender: str = "Unknown") -> dict:
    from .models import get_model
    m = get_model()
    case = dict(DiagnosisCategory=DiagnosisCategory, DiagnosisSubCategory=DiagnosisSubCategory, TreatmentCategory=TreatmentCategory,
                TreatmentSubCategory=TreatmentSubCategory, Type=Type, IMRType=IMRType, AgeRange=AgeRange, PatientGender=PatientGender)
    p = m.predict(case)
    unseen = TreatmentCategory not in m.report["treatment_categories_seen"]
    return {"overturn_probability": round(p, 4), "overturn_percent": round(100 * p, 1), "band": m.band(p),
            "train_overturn_rate": m.report["data"]["train_overturn_rate"], "model": m.report["served_model"],
            "test_roc_auc": m.report["test_metrics"]["roc_auc"], "test_brier": m.report["test_metrics"]["brier"],
            "treatment_category_unseen": unseen,
            "limit": m.report["limits"]}


def classify_request_text(text: str) -> dict:
    from .text_model import classify_request
    return classify_request(text[:600])


def cohort_stats(treatment_category: str | None = None, review_type: str | None = None, diagnosis_category: str | None = None,
                 before_year: int | None = None) -> dict:
    from .stats import cohort_stats as _cs
    return _cs(treatment_category, review_type, diagnosis_category, before_year)


def hypothesis_tests() -> dict:
    from .stats import all_tests
    t = all_tests()
    return {k: ({kk: vv for kk, vv in v.items() if kk not in ("rates", "by_year")} if isinstance(v, dict) else v) for k, v in t.items()}


def graph_neighbors(treatment_subcategory: str, k: int = 5) -> dict:
    """Coverage graph walk: treatment subcategory -> diagnosis categories (IMR co-occurrence, with overturn rates) -> NCD documents."""
    d = load_imr()
    sub = d[d.TreatmentSubCategory == treatment_subcategory]
    if sub.empty:
        return {"error": f"unknown TreatmentSubCategory {treatment_subcategory!r}"}
    g = sub.groupby("DiagnosisCategory").overturned.agg(["count", "mean"]).sort_values("count", ascending=False).head(k)
    ncds: list[dict] = []
    for h in get_index().search(treatment_subcategory, 8):
        if h["doc_id"] not in [n["doc_id"] for n in ncds]:
            ncds.append({"doc_id": h["doc_id"], "title": h["title"]})
    return {"node": {"type": "treatment", "id": treatment_subcategory, "imr_cases": int(len(sub))},
            "edges": {"treatment->diagnosis": [{"diagnosis": i, "cases": int(r["count"]), "overturn_rate": round(float(r["mean"]), 3)} for i, r in g.iterrows()],
                      "treatment->policy": ncds[:k]},
            "graph": "nodes: treatment subcategory, diagnosis category, policy document; edges from IMR co-occurrence and policy retrieval"}


def scan_documents(texts: list[str]) -> dict:
    return _scan([t[:4000] for t in texts[:12]])


RULE_CONFIRM = {
    2: r"\[(NCD|LCD|IMR)-",
    3: r"\b(doctor|physician|attorney|lawyer|counsel|m\.?d\.?|health plan|insurer|on behalf of the plan)\b",
    4: r"\b(guarantee\w*|certain(ly)?|definitely|will be (overturned|approved)|assured|sure to)\b",
    5: r"\b(legal advice|medical advice|no need to (consult|see)|do not (need to )?consult)\b",
    6: r"(@|\b\d{3}-\d{2}-\d{4}\b|\b(mr|mrs|ms|dr)\.? [A-Z]|member id|date of birth)",
}


ABSENCE = (r"\b(no (information|documentation|details?|evidence|records?)\b.{0,40}\b(provided|available|documented|given|included)|"
           r"(not|never) (been )?(specified|documented|provided|stated|included)|do(es)? not (specify|state|include|mention)|"
           r"unclear (if|whether)|to clarify whether|(must|should|needs? to|will need to) be (documented|confirmed|provided))\b")
CITE_RX = re.compile(r"\[((?:NCD|LCD)-[A-Z]?[\d.]+(?::\d+)?|IMR-[A-Z]{2}\d{2}-\d+)\]")
STOP = set("the a an of to and or for in on with by is are be this that as at from it its was were which when not no any all must will may can "
           "has have had been their there these those such than then also only if under per".split())


def _content(t: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z\-]{2,}", t.lower()) if w not in STOP}


def citation_unsupported(sentence: str) -> bool:
    """Code check for red-team rule 2. A cited sentence is confirmed as unsupported only when a cited id does not exist, an
    inline double-quoted span is not verbatim in the cited excerpt, or (with no inline quote) the sentence shares under 15% of
    its content words with the cited excerpt. A sentence without any citation is not a rule-2 issue (rule 2 is about wrong ids)."""
    ids = CITE_RX.findall(sentence)
    if not ids:
        return False
    by_id = get_index().by_id
    texts = []
    for cid in ids:
        if cid.startswith("IMR-"):
            if cid[4:] not in set(load_imr().ReferenceID):
                return True
            continue
        chunk = by_id.get(cid) or next((c for c in get_index().chunks if c["doc_id"] == cid), None)
        if chunk is None:
            return True
        texts.append(chunk["text"] if cid in by_id else " ".join(c["text"] for c in get_index().chunks if c["doc_id"] == cid))
    if not texts:
        return False
    body = norm(" ".join(texts))
    quoted = [q for q in re.findall(r"[\"\u201c]([^\"\u201d]{15,})[\"\u201d]", sentence)]
    if quoted:
        return any(norm(q).rstrip(".,;: ") not in body for q in quoted)
    words = _content(CITE_RX.sub(" ", sentence))
    return bool(words) and len(words & _content(body)) / len(words) < 0.15


def confirm_red_team(issues: list[dict], draft: str) -> dict:
    """LLM proposes, code confirms: keep only issues whose quote really occurs in the draft AND (for rules with an observable
    surface form) shows that form. Rule 8 (missing disclaimer) is confirmed only if the disclaimer is really missing."""
    from .harness import DISCLAIMER_PATTERNS
    from .prompts import DISCLAIMER
    disc = norm(DISCLAIMER)
    d = norm(draft)
    has_disclaimer = all(re.search(p, (draft or "").lower()) for p in DISCLAIMER_PATTERNS)
    kept: list[dict] = []
    dropped: list[dict] = []
    for i in issues or []:
        rule = int(i.get("rule", 0) or 0)
        quote = str(i.get("quote", ""))
        q = norm(quote)
        ok = 1 <= rule <= 8 and len(q) >= 12 and q in d and q not in disc      # the fixed disclaimer is code-owned text
        if ok and rule in RULE_CONFIRM:
            ok = bool(re.search(RULE_CONFIRM[rule], quote, re.I))
        if ok and rule == 8:
            ok = not has_disclaimer
        if ok and rule == 1:
            ok = not re.search(ABSENCE, quote, re.I)        # saying a fact is missing does not invent one
        if ok and rule == 2:
            ok = citation_unsupported(quote)
        (kept if ok else dropped).append(i)
    return {"verdict": "fail" if kept else "pass", "issues": [f"rule {i['rule']}: \"{str(i['quote'])[:160]}\"" for i in kept],
            "dropped_unverifiable": len(dropped),
            "dropped": [f"rule {i.get('rule')}: \"{str(i.get('quote', ''))[:120]}\"" for i in dropped][:6]}


def dataset_card() -> dict:
    m = manifest()
    return {"counts": m["counts"], "sources": {k: {kk: v.get(kk) for kk in ("name", "page", "license", "sha256", "fetched")} for k, v in m["sources"].items()},
            "feed_versions": feed_versions(), "cleaning_log": m["cleaning_log"]}


def model_card() -> dict:
    from .models import get_model
    r = get_model().report
    return {k: r[k] for k in ("task", "features", "excluded_features", "split", "data", "selected", "served_model", "test_metrics",
                              "baselines_on_test", "calibration_curve_test", "limits")}
