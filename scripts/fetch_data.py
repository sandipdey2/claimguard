"""Download the public sources into data/raw/ (gitignored), then rebuild the cleaned snapshot in data/snapshot/.

    python scripts/fetch_data.py                 # download missing files, rebuild snapshot, print checksums
    python scripts/fetch_data.py --refresh       # re-download everything
    python scripts/fetch_data.py --with-lcd      # also fetch the optional LCD export (local index only; never committed)
    python scripts/fetch_data.py --verify        # only verify data/snapshot against manifest.json

Sources, URLs and licenses: claimguard/data.py SOURCES and docs/DATA_SOURCES.md.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from claimguard.config import RAW  # noqa: E402
from claimguard.data import SOURCES, build_snapshot, file_sha256, verify_snapshot  # noqa: E402

UA = {"User-Agent": "ClaimGuard-data-fetch/0.1 (+https://github.com/sandipdey2/claimguard)"}


def download(url: str, dest: Path) -> None:
    tmp = dest.with_suffix(dest.suffix + ".part")
    with httpx.stream("GET", url, headers=UA, follow_redirects=True, timeout=httpx.Timeout(30, read=300)) as r:
        r.raise_for_status()
        with open(tmp, "wb") as fh:
            for chunk in r.iter_bytes(1 << 20):
                fh.write(chunk)
    tmp.replace(dest)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--with-lcd", action="store_true")
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()
    if a.verify:
        res = verify_snapshot()
        print(json.dumps(res, indent=1))
        return 0 if res.get("ok") else 1
    RAW.mkdir(parents=True, exist_ok=True)
    for key, s in SOURCES.items():
        if s.get("optional") and not a.with_lcd:
            continue
        dest = RAW / s["file"]
        if dest.exists() and not a.refresh:
            print(f"keep  {s['file']:<16} {dest.stat().st_size:>11,d} B")
            continue
        print(f"fetch {s['file']:<16} <- {s['url']}")
        download(s["url"], dest)
    m = build_snapshot()
    for name, src in m["sources"].items():
        print(f"{name:<24} {src['bytes']:>11,d} B sha256 {src['sha256'][:16]}...")
    print(json.dumps(m["counts"], indent=1))
    for f in sorted(RAW.iterdir()):
        if f.is_file():
            print(f"raw {f.name}: sha256 {file_sha256(f)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
