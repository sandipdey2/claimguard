"""Receipt and run-log storage: local files by default; Azure Blob Storage when AZURE_STORAGE_ACCOUNT_URL (managed identity)
or AZURE_STORAGE_CONNECTION_STRING is set (optional ``azure-storage-blob`` / ``azure-identity``). Blob failures fall back to
local files and say so in the return value."""
from __future__ import annotations

import json
from pathlib import Path

from .config import RUNTIME, secret

CONTAINER = "receipts"


def _blob_client():
    from azure.storage.blob import BlobServiceClient  # type: ignore[import-not-found]
    conn = secret("AZURE_STORAGE_CONNECTION_STRING")
    if conn:
        return BlobServiceClient.from_connection_string(conn)
    from azure.identity import DefaultAzureCredential  # type: ignore[import-not-found]
    return BlobServiceClient(account_url=secret("AZURE_STORAGE_ACCOUNT_URL") or "", credential=DefaultAzureCredential())


def save_json(name: str, obj: dict, local_dir: Path | None = None) -> dict:
    data = json.dumps(obj, indent=1, default=str)
    if secret("AZURE_STORAGE_ACCOUNT_URL") or secret("AZURE_STORAGE_CONNECTION_STRING"):
        try:
            c = _blob_client().get_container_client(secret("AZURE_STORAGE_CONTAINER", CONTAINER))
            c.upload_blob(name, data.encode(), overwrite=False)
            return {"backend": "azure_blob", "name": name}
        except Exception as exc:
            fallback = f"local (azure_blob failed: {type(exc).__name__})"
        else:  # pragma: no cover
            fallback = "local"
    else:
        fallback = "local"
    d = local_dir or (RUNTIME / "receipts")
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(data, encoding="utf-8")
    return {"backend": fallback, "path": str(p)}
