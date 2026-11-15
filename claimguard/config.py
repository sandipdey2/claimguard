"""Configuration: paths, the run contract, secrets and provider settings.

Secrets are read from Streamlit secrets, then the environment (which Azure Container Apps fills from Key Vault
references). Nothing here prints or logs a secret value.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"                      # git-ignored full downloads (scripts/fetch_data.py)
SNAPSHOT = DATA / "snapshot"            # committed, checksummed snapshot used by the app, tests and eval
RUNTIME = Path(os.environ.get("CG_RUNTIME_DIR", str(DATA / "runtime")))   # git-ignored caches, receipts, model files
CONTRACT_PATH = ROOT / "contract.json"
EVAL = ROOT / "eval"
LOGS = EVAL / "logs"

MODEL = "gpt-4o-mini"                   # the only model ClaimGuard is allowed to call
DEFAULT_VOCAREUM_BASE = "https://openai.vocareum.com/v1"
DEFAULT_AZURE_API_VERSION = "2024-10-21"


def _from_streamlit(name: str) -> str | None:
    try:
        import streamlit as st
        v = st.secrets.get(name)        # raises when no secrets file exists
        return str(v) if v is not None else None
    except Exception:
        return None


def secret(name: str, default: str | None = None) -> str | None:
    return _from_streamlit(name) or os.environ.get(name) or default


@lru_cache(maxsize=1)
def load_contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def provider() -> str:
    p = (secret("CG_LLM_PROVIDER", "vocareum") or "vocareum").strip().lower()
    if p not in ("vocareum", "azure"):
        raise ValueError(f"CG_LLM_PROVIDER must be 'vocareum' or 'azure', not {p!r}")
    return p


def azure_flags() -> dict[str, bool]:
    """Which Azure adapters are configured (True) or fall back to the local equivalent (False). Values are never returned."""
    return {
        "azure_openai": bool(secret("AZURE_OPENAI_ENDPOINT") and secret("AZURE_OPENAI_DEPLOYMENT")),
        "ai_search": bool(secret("AZURE_SEARCH_ENDPOINT") and secret("AZURE_SEARCH_INDEX")),
        "blob": bool(secret("AZURE_STORAGE_ACCOUNT_URL") or secret("AZURE_STORAGE_CONNECTION_STRING")),
        "content_safety": bool(secret("AZURE_CONTENT_SAFETY_ENDPOINT")),
        "app_insights": bool(secret("APPLICATIONINSIGHTS_CONNECTION_STRING")),
        "key_vault": bool(secret("AZURE_KEY_VAULT_URL")),
    }


def _azure_token_provider():
    """Microsoft Entra ID (managed identity) token provider when no API key is set; requires azure-identity."""
    from azure.identity import DefaultAzureCredential, get_bearer_token_provider  # type: ignore[import-not-found]
    return get_bearer_token_provider(DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default")


def get_llm(http_async_client=None):
    """gpt-4o-mini through Vocareum (OpenAI-compatible) or Azure OpenAI in Azure AI Foundry (CG_LLM_PROVIDER)."""
    c = load_contract()
    extra = {"http_async_client": http_async_client} if http_async_client is not None else {}
    common = dict(temperature=c["temperature"], top_p=c.get("top_p", 1.0), timeout=c["llm_timeout_s"], max_retries=2, **extra)
    if provider() == "azure":
        from langchain_openai import AzureChatOpenAI
        endpoint, deployment = secret("AZURE_OPENAI_ENDPOINT"), secret("AZURE_OPENAI_DEPLOYMENT")
        if not (endpoint and deployment):
            raise RuntimeError("CG_LLM_PROVIDER=azure needs AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_DEPLOYMENT (Key Vault or env).")
        model_name = secret("AZURE_OPENAI_MODEL", MODEL)
        if model_name != MODEL:
            raise RuntimeError(f"ClaimGuard only runs {MODEL}; AZURE_OPENAI_MODEL is {model_name!r}")
        key = secret("AZURE_OPENAI_API_KEY")
        auth = {"api_key": key} if key else {"azure_ad_token_provider": _azure_token_provider()}
        return AzureChatOpenAI(azure_endpoint=endpoint, azure_deployment=deployment, model=MODEL,
                               api_version=secret("AZURE_OPENAI_API_VERSION", DEFAULT_AZURE_API_VERSION), **auth, **common)
    from langchain_openai import ChatOpenAI
    key = secret("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not set (Streamlit secrets or environment).")
    from pydantic import SecretStr
    return ChatOpenAI(model=MODEL, api_key=SecretStr(key), base_url=secret("OPENAI_API_BASE", DEFAULT_VOCAREUM_BASE), **common)


def llm_available() -> bool:
    try:
        if provider() == "azure":
            return azure_flags()["azure_openai"]
        return bool(secret("OPENAI_API_KEY"))
    except ValueError:
        return False
