# Data sources, licenses and cleaning

All data is public. ClaimGuard uses **no synthetic records and no PHI**. Raw downloads go to `data/raw/` (gitignored, fetched by `scripts/fetch_data.py`). The cleaned snapshot is in `data/snapshot/`, with sha256 checksums for every source and snapshot file in `manifest.json`. Every receipt carries these feed versions.

| Key | Source | Raw file | License / terms |
|---|---|---|---|
| ca_dmhc_imr | [CA DMHC IMR determinations](https://data.ca.gov/dataset/independent-medical-review-imr-determinations-trend) | imr.csv (85.4 MB) | data.ca.gov open data (Creative Commons Attribution); CHHS Open Data Terms; attribution: California Department of Managed Health Care |
| ny_dfs_external_appeals | [NY DFS external appeal search](https://www.dfs.ny.gov/public-appeal/search) (all-years export) | dfs.xlsx (2.9 MB) | public records of the NY Department of Financial Services; attribution kept; check the portal terms before commercial reuse |
| cms_ncd | [CMS MCD downloads](https://www.cms.gov/medicare-coverage-database/downloads/downloads.aspx), NCD export | ncd.zip | U.S. federal government work; only the NCD narrative is used |
| cms_ncd_api | [CMS Coverage API](https://api.coverage.cms.gov/) national NCD report | ncd_api.json | U.S. federal government work |
| cms_lcd (optional) | CMS current LCD export | current_lcd.zip | may reference AMA CPT / ADA CDT / AHA material; **indexed locally only with `CG_INCLUDE_LCD=1`, CPT-like codes masked, never committed or redistributed** |

## Cleaning (logged step by step in manifest.json `cleaning_log`)

- **IMR:** 42,749 raw rows → 42,710 after dropping 39 exact duplicates.
  - The label `overturned` is set when the Determination starts with "Overturned".
  - The pre-decision request sentence (`request_text`, "has requested …") is extracted from Findings for 35,620 rows.
  - Full Findings text is kept only for 2023+ (8,229 rows), for size.
  - DMHC already de-identifies these records.
- **DFS:** 63,499 → 62,249 rows after dropping 1,250 exact duplicates. Decisions: Upheld 32,463, Overturned 28,610, Overturned in Part 1,176.
- **NCD:** 357 → 345 current (terminated NCDs dropped), all 345 matched to the Coverage API.
  - HTML is converted to text.
  - Mixed latin-1/UTF-8 text is repaired (`fix_mojibake`).
  - The text is chunked with LangChain RecursiveCharacterTextSplitter into 1,034 chunks with ids like `NCD-280.14:3`.

## How the data is used

- **Demo cases.** These are six real 2025 IMR rows. The agents receive the case categories and the request sentence. The published Determination and the Findings are **held out** and appear only afterwards in the log, for scoring.
- **Precedents.** They are only decisions published before the case year, and never the case itself.
- **Models.** The 2026 rows (an incomplete year) are excluded.
