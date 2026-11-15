"""Project 1 lineage: a logged, reproducible ingest pipeline for the public sources.

Raw files (large) are downloaded by ``scripts/fetch_data.py`` into data/raw/ (git-ignored). ``build_snapshot``
cleans them with logged steps and writes a small, checksummed snapshot to data/snapshot/ that is committed and
used by the app, the MCP server, the tests and the evaluation. No synthetic rows are ever created.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

from .config import RAW, SNAPSHOT

SOURCES: dict[str, dict[str, Any]] = {
    "ca_dmhc_imr": {
        "name": "California DMHC Independent Medical Review (IMR) Determinations",
        "url": "https://data.chhs.ca.gov/dataset/b79b3447-4c10-4ae6-84e2-1076f83bb24e/resource/3340c5d7-4054-4d03-90e0-5f44290ed095/download/independent-medical-review-imr-determinations-trends.csv",
        "page": "https://data.ca.gov/dataset/independent-medical-review-imr-determinations-trend",
        "file": "imr.csv",
        "license": "Creative Commons Attribution (data.ca.gov); CHHS Open Data Terms of Use. Attribution: California Department of Managed Health Care.",
    },
    "ny_dfs_external_appeals": {
        "name": "New York DFS External Appeal Database (closed appeals, all years export)",
        "url": "https://myportal.dfs.ny.gov/o/peasa/peasaserviceexcel",
        "page": "https://www.dfs.ny.gov/public-appeal/search",
        "file": "dfs.xlsx",
        "license": "Public government records published by the New York State Department of Financial Services; attribution kept. Confirm portal terms before commercial reuse.",
    },
    "cms_ncd": {
        "name": "CMS Medicare Coverage Database - National Coverage Determinations (weekly export)",
        "url": "https://downloads.cms.gov/medicare-coverage-database/downloads/exports/ncd.zip",
        "page": "https://www.cms.gov/medicare-coverage-database/downloads/downloads.aspx",
        "file": "ncd.zip",
        "license": "U.S. federal government work (CMS), public information. NCD narrative only; no AMA CPT code sets are redistributed.",
    },
    "cms_ncd_api": {
        "name": "CMS Coverage API - national NCD report",
        "url": "https://api.coverage.cms.gov/v1/reports/national-coverage-ncd/",
        "page": "https://api.coverage.cms.gov/",
        "file": "ncd_api.json",
        "license": "U.S. federal government work (CMS), public information.",
    },
    "cms_lcd": {
        "name": "CMS Medicare Coverage Database - current Local Coverage Determinations (optional)",
        "url": "https://downloads.cms.gov/medicare-coverage-database/downloads/exports/current_lcd.zip",
        "page": "https://www.cms.gov/medicare-coverage-database/downloads/downloads.aspx",
        "file": "current_lcd.zip",
        "license": "CMS public information, but LCD files can reference AMA CPT / ADA CDT / AHA content. ClaimGuard indexes LCD narrative locally only "
                   "and never commits or redistributes LCD text or code lists.",
        "optional": True,
    },
}
IMR_FINDINGS_FROM_YEAR = 2023          # full Findings text is committed only for recent years (size); all rows keep the request text
REQUEST_RX = re.compile(r"(?:has|have|had)\s+requested\s+([^.]{8,400})\.", re.I)
TAG_RX = re.compile(r"<[^>]+>")


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def html_to_text(s) -> str:
    if not isinstance(s, str):
        return ""
    s = re.sub(r"(?i)<\s*(br|/p|/li|/h\d|/tr)\s*/?>", "\n", s)
    s = re.sub(r"(?i)<\s*li[^>]*>", "\n- ", s)
    s = html.unescape(TAG_RX.sub(" ", s))
    s = s.replace("\xa0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n\s*\n+", "\n\n", s)
    return s.strip()


def request_text(findings: str) -> str:
    """The pre-decision part of a published IMR: what was requested (no reviewer conclusion)."""
    m = REQUEST_RX.search(findings or "")
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


class StepLog:
    """P1-style cleaning log: every step records rows in/out and why."""

    def __init__(self) -> None:
        self.steps: list[dict] = []

    def add(self, dataset: str, step: str, rows_in: int, rows_out: int, note: str = "") -> None:
        self.steps.append({"dataset": dataset, "step": step, "rows_in": int(rows_in), "rows_out": int(rows_out), "note": note})


def _clean_imr(raw: Path, log: StepLog) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = pd.read_csv(raw)
    n0 = len(df)
    log.add("ca_dmhc_imr", "read_csv", n0, n0, f"{len(df.columns)} columns")
    df = df.drop_duplicates()
    log.add("ca_dmhc_imr", "drop_exact_duplicate_rows", n0, len(df), "the published CSV repeats some rows verbatim")
    assert df.ReferenceID.is_unique, "ReferenceID must be unique after removing exact duplicates"
    for c in ["DiagnosisCategory", "DiagnosisSubCategory", "TreatmentCategory", "TreatmentSubCategory", "AgeRange", "PatientGender"]:
        df[c] = df[c].fillna("Unknown").astype(str).str.strip()
    log.add("ca_dmhc_imr", "fill_missing_categoricals_with_Unknown", len(df), len(df),
            "AgeRange/PatientGender missing on 691 rows are kept as 'Unknown' (not imputed)")
    df["overturned"] = df["Determination"].str.startswith("Overturned").astype(int)
    df["request_text"] = df["Findings"].map(request_text)
    df["findings_chars"] = df["Findings"].fillna("").str.len()
    log.add("ca_dmhc_imr", "derive_label_and_request_text", len(df), len(df),
            f"request_text found on {int((df.request_text != '').sum())} rows; label overturned = Determination starts with 'Overturned'")
    slim = df.drop(columns=["Findings"])
    recent = df.loc[df.ReportYear >= IMR_FINDINGS_FROM_YEAR, ["ReferenceID", "ReportYear", "Findings"]].copy()
    log.add("ca_dmhc_imr", f"keep_full_findings_for_years>={IMR_FINDINGS_FROM_YEAR}", len(df), len(recent), "size limit for the committed snapshot")
    return slim, recent


def _clean_dfs(raw: Path, log: StepLog) -> pd.DataFrame:
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        d = pd.read_excel(raw)
    n0 = len(d)
    log.add("ny_dfs_external_appeals", "read_excel", n0, n0, f"{len(d.columns)} columns")
    d.columns = [c.strip().lower().replace(" ", "_") for c in d.columns]
    for c in ["diagnosis", "treatment"]:
        d[c] = d[c].astype(str).str.strip("[]").str.strip()
    d = d.drop_duplicates()
    log.add("ny_dfs_external_appeals", "drop_exact_duplicate_rows", n0, len(d), "the export repeats some rows verbatim")
    assert d.case_number.is_unique, "Case Number must be unique after removing exact duplicates"
    d["overturned_any"] = d["decision"].isin(["Overturned", "Overturned in Part"]).astype(int)
    d["overturned_full"] = (d["decision"] == "Overturned").astype(int)
    log.add("ny_dfs_external_appeals", "derive_labels", len(d), len(d), "overturned_any includes 'Overturned in Part'; overturned_full does not")
    return d


def _clean_ncd(raw_zip: Path, api_json: Path | None, log: StepLog) -> pd.DataFrame:
    import io
    import zipfile
    z = zipfile.ZipFile(raw_zip)
    inner = zipfile.ZipFile(io.BytesIO(z.read("ncd_csv.zip")))
    d = pd.read_csv(io.BytesIO(inner.read("ncd_trkg.csv")), encoding="latin-1")
    n0 = len(d)
    log.add("cms_ncd", "read_ncd_trkg", n0, n0)
    d = d[d["NCD_trmntn_dt"].isna()].copy()
    log.add("cms_ncd", "drop_terminated", n0, len(d), "NCDs with a termination date are excluded from retrieval")
    if api_json and api_json.exists():
        api = {str(r["document_display_id"]): r for r in json.loads(api_json.read_text())["data"]}
        d["api_last_updated"] = d["NCD_mnl_sect"].astype(str).map(lambda s: (api.get(s) or {}).get("last_updated"))
        d["api_document_id"] = d["NCD_mnl_sect"].astype(str).map(lambda s: (api.get(s) or {}).get("document_id"))
        log.add("cms_ncd", "join_coverage_api_report", len(d), len(d), f"{int(d.api_document_id.notna().sum())} matched the API report ({len(api)} NCDs)")
    out = pd.DataFrame({
        "ncd_id": d["NCD_mnl_sect"].astype(str), "title": d["NCD_mnl_sect_title"].astype(str),
        "version": d["NCD_vrsn_num"], "effective": d["NCD_efctv_dt"].astype(str).str[:10],
        "item_service": d["itm_srvc_desc"].map(html_to_text), "indications_limitations": d["indctn_lmtn"].map(html_to_text),
        "cross_reference": d["xref_txt"].map(html_to_text),
        "cms_document_id": d.get("api_document_id"), "api_last_updated": d.get("api_last_updated"),
    })
    out["url"] = out["cms_document_id"].map(lambda i: f"https://www.cms.gov/medicare-coverage-database/view/ncd.aspx?ncdid={int(i)}" if pd.notna(i) else "")
    return out.sort_values("ncd_id").reset_index(drop=True)


def build_snapshot(raw_dir: Path = RAW, out_dir: Path = SNAPSHOT) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    log = StepLog()
    slim, recent = _clean_imr(raw_dir / "imr.csv", log)
    slim.to_parquet(out_dir / "imr_slim.parquet", index=False, compression="zstd")
    recent.to_parquet(out_dir / "imr_findings_recent.parquet", index=False, compression="zstd")
    dfs = _clean_dfs(raw_dir / "dfs.xlsx", log)
    dfs.to_parquet(out_dir / "dfs.parquet", index=False, compression="zstd")
    ncd = _clean_ncd(raw_dir / "ncd.zip", raw_dir / "ncd_api.json", log)
    ncd.to_parquet(out_dir / "ncd.parquet", index=False, compression="zstd")
    manifest: dict[str, Any] = {"built_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "sources": {}, "snapshot_files": {}, "cleaning_log": log.steps,
                "counts": {"imr_rows": len(slim), "imr_overturned": int(slim.overturned.sum()), "imr_upheld": int((1 - slim.overturned).sum()),
                           "imr_years": [int(slim.ReportYear.min()), int(slim.ReportYear.max())], "imr_findings_rows": len(recent),
                           "dfs_rows": len(dfs), "dfs_decisions": dfs.decision.value_counts().to_dict(),
                           "dfs_years": [int(dfs.decision_year.min()), int(dfs.decision_year.max())], "ncd_current": len(ncd)}}
    for key, s in SOURCES.items():
        p = raw_dir / s["file"]
        if p.exists():
            manifest["sources"][key] = {**{k: v for k, v in s.items() if k != "file"}, "raw_file": s["file"], "bytes": p.stat().st_size,
                                        "sha256": file_sha256(p), "fetched": time.strftime("%Y-%m-%d", time.localtime(p.stat().st_mtime))}
    for f in sorted(out_dir.glob("*.parquet")):
        manifest["snapshot_files"][f.name] = {"bytes": f.stat().st_size, "sha256": file_sha256(f)}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1, default=str), encoding="utf-8")
    return manifest


# ----------------------------------------------------------------------------- loaders (snapshot)
@lru_cache(maxsize=1)
def manifest() -> dict:
    return json.loads((SNAPSHOT / "manifest.json").read_text(encoding="utf-8"))


def verify_snapshot() -> dict:
    """Recompute every committed snapshot checksum against the manifest."""
    m = manifest()
    bad = [n for n, v in m["snapshot_files"].items() if file_sha256(SNAPSHOT / n) != v["sha256"]]
    return {"ok": not bad, "mismatched": bad, "files": len(m["snapshot_files"])}


def feed_versions() -> dict:
    m = manifest()
    return {k: v["sha256"][:16] for k, v in m["snapshot_files"].items()}


@lru_cache(maxsize=1)
def load_imr() -> pd.DataFrame:
    return pd.read_parquet(SNAPSHOT / "imr_slim.parquet")


@lru_cache(maxsize=1)
def load_imr_findings() -> dict[str, str]:
    f = pd.read_parquet(SNAPSHOT / "imr_findings_recent.parquet")
    return dict(zip(f.ReferenceID, f.Findings))


@lru_cache(maxsize=1)
def load_dfs() -> pd.DataFrame:
    return pd.read_parquet(SNAPSHOT / "dfs.parquet")


@lru_cache(maxsize=1)
def load_ncd() -> pd.DataFrame:
    return pd.read_parquet(SNAPSHOT / "ncd.parquet")


def imr_case(reference_id: str) -> dict | None:
    df = load_imr()
    hit = df[df.ReferenceID == reference_id.strip()]
    if hit.empty:
        return None
    row = {k: (v.item() if hasattr(v, "item") else v) for k, v in hit.iloc[0].to_dict().items()}
    row["Findings"] = load_imr_findings().get(reference_id.strip())
    row["source_url"] = "https://wpso.dmhc.ca.gov/imr/"
    return row


def dfs_case(case_number: str) -> dict | None:
    d = load_dfs()
    hit = d[d.case_number.astype(str) == case_number.strip()]
    if hit.empty:
        return None
    return {k: (v.item() if hasattr(v, "item") else v) for k, v in hit.iloc[0].to_dict().items()}


def lcd_raw_path() -> Path | None:
    p = RAW / "current_lcd.zip"
    return p if p.exists() else None
