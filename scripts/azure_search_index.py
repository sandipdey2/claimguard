"""Create the Azure AI Search index and upload the NCD chunks with their 256-d LSA vectors (the same vectors the query side
computes locally, so hybrid keyword + vector search matches the local index).

    python scripts/azure_search_index.py              # dry run: writes docs/azure_search_index.json, uploads nothing
    python scripts/azure_search_index.py --push       # needs AZURE_SEARCH_ENDPOINT (+ API key or Entra role Search Index Data Contributor)

Document keys cannot contain ':' or '.', so the key is a sanitised copy of the chunk id; the original id stays in field "id".
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from claimguard.config import secret  # noqa: E402
from claimguard.retrieval import get_index  # noqa: E402

API = "2024-07-01"


def schema(name: str, dims: int) -> dict:
    s = {"type": "Edm.String", "searchable": False, "filterable": True, "retrievable": True}
    return {"name": name, "fields": [
        {"name": "key", "type": "Edm.String", "key": True, "filterable": True},
        {**s, "name": "id"}, {**s, "name": "doc_id"}, {**s, "name": "doc_type"},
        {"name": "title", "type": "Edm.String", "searchable": True, "retrievable": True},
        {"name": "text", "type": "Edm.String", "searchable": True, "retrievable": True, "analyzer": "en.lucene"},
        {**s, "name": "url"}, {**s, "name": "effective"}, {"name": "version", "type": "Edm.Int32", "filterable": True, "retrievable": True},
        {"name": "embedding", "type": "Collection(Edm.Single)", "searchable": True, "retrievable": False, "dimensions": dims, "vectorSearchProfile": "lsa"}],
        "vectorSearch": {"algorithms": [{"name": "hnsw", "kind": "hnsw", "hnswParameters": {"metric": "cosine"}}],
                         "profiles": [{"name": "lsa", "algorithm": "hnsw"}]},
        "semantic": {"configurations": [{"name": "default", "prioritizedFields": {"titleField": {"fieldName": "title"},
                                                                                  "prioritizedContentFields": [{"fieldName": "text"}]}}]}}


def docs() -> list[dict]:
    ix = get_index()
    return [{"@search.action": "mergeOrUpload", "key": re.sub(r"[^A-Za-z0-9_\-=]", "_", c["id"]), **{k: c.get(k) for k in ("id", "doc_id", "doc_type", "title", "text", "url", "effective")},
             "version": int(c.get("version") or 0), "embedding": [round(float(x), 6) for x in ix.V[i]]} for i, c in enumerate(ix.chunks)]


def headers() -> dict:
    key = secret("AZURE_SEARCH_API_KEY")
    if key:
        return {"Content-Type": "application/json", "api-key": key}
    from azure.identity import DefaultAzureCredential
    return {"Content-Type": "application/json", "Authorization": "Bearer " + DefaultAzureCredential().get_token("https://search.azure.com/.default").token}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--push", action="store_true")
    a = ap.parse_args()
    name = secret("AZURE_SEARCH_INDEX", "claimguard-policy") or "claimguard-policy"
    d = docs()
    sch = schema(name, len(d[0]["embedding"]))
    (ROOT / "docs" / "azure_search_index.json").write_text(json.dumps(sch, indent=1), encoding="utf-8")
    keys = {x["key"] for x in d}
    assert len(keys) == len(d), "document keys must be unique"
    print(f"index {name}: {len(d)} documents, {len(d[0]['embedding'])}-d vectors; schema -> docs/azure_search_index.json")
    if not a.push:
        print("dry run (use --push to create the index and upload)")
        return 0
    ep = (secret("AZURE_SEARCH_ENDPOINT") or "").rstrip("/")
    if not ep:
        sys.exit("AZURE_SEARCH_ENDPOINT is not set")
    h = headers()
    httpx.put(f"{ep}/indexes/{name}?api-version={API}", headers=h, json=sch, timeout=60).raise_for_status()
    for i in range(0, len(d), 500):
        httpx.post(f"{ep}/indexes/{name}/docs/index?api-version={API}", headers=h, json={"value": d[i:i + 500]}, timeout=120).raise_for_status()
    print("uploaded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
