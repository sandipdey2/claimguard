"""Offline tests of the env-gated Azure adapters: each one is exercised against a mocked HTTP endpoint, and each falls back to
the local path when unset or failing. No network, no Azure subscription."""
import httpx
import pytest

from claimguard import guard, retrieval, storage
from claimguard.config import azure_flags, get_llm


class Resp:
    def __init__(self, payload, status=200):
        self.payload, self.status_code = payload, status

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=httpx.Request("POST", "https://x"), response=httpx.Response(self.status_code))


def test_flags_are_booleans_and_off_by_default():
    f = azure_flags()
    assert f and all(v is False for v in f.values())


def test_prompt_shields_blocks_document_attack(monkeypatch):
    seen = {}

    def fake_post(url, headers, json, timeout):
        seen.update(url=url, headers=headers, body=json)
        return Resp({"userPromptAnalysis": {"attackDetected": False}, "documentsAnalysis": [{"attackDetected": True}]})

    monkeypatch.setenv("AZURE_CONTENT_SAFETY_ENDPOINT", "https://cs.example.cognitiveservices.azure.com/")
    monkeypatch.setenv("AZURE_CONTENT_SAFETY_KEY", "test-only-key")
    monkeypatch.setattr(httpx, "post", fake_post)
    r = guard.check_input("Draft an appeal letter for this denied claim.", "The health plan denied a request for a cochlear implant.")
    assert not r["allowed"] and r["reason"] == "prompt_injection" and r["prompt_shields"]["status"] == "OK"
    assert seen["url"].endswith("/contentsafety/text:shieldPrompt?api-version=2024-09-01") and "Ocp-Apim-Subscription-Key" in seen["headers"]
    assert seen["body"]["documents"] == ["The health plan denied a request for a cochlear implant."]


def test_prompt_shields_error_does_not_block_and_is_reported(monkeypatch):
    monkeypatch.setenv("AZURE_CONTENT_SAFETY_ENDPOINT", "https://cs.example.cognitiveservices.azure.com/")
    monkeypatch.setenv("AZURE_CONTENT_SAFETY_KEY", "test-only-key")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: Resp({}, 503))
    r = guard.check_input("Draft an appeal letter for this denied claim.", "The plan denied an MRI.")
    assert r["allowed"] and r["prompt_shields"]["status"] == "ERROR"


def test_azure_search_hybrid_query_and_fallback(monkeypatch):
    seen = {}

    def fake_post(url, headers, json, timeout):
        seen.update(url=url, body=json, headers=headers)
        return Resp({"value": [{"id": "NCD-50.3:1", "doc_id": "NCD-50.3", "doc_type": "NCD", "title": "Cochlear Implantation", "text": "t",
                                "@search.score": 0.03, "@search.rerankerScore": 2.9}]})

    monkeypatch.setenv("AZURE_SEARCH_ENDPOINT", "https://s.search.windows.net")
    monkeypatch.setenv("AZURE_SEARCH_INDEX", "claimguard-policy")
    monkeypatch.setenv("AZURE_SEARCH_API_KEY", "test-only-key")
    monkeypatch.setenv("AZURE_SEARCH_SEMANTIC_CONFIG", "default")
    monkeypatch.setattr(httpx, "post", fake_post)
    r = retrieval.search_policy("cochlear implant", 3)
    assert r["backend"] == "azure_ai_search" and r["results"][0]["id"] == "NCD-50.3:1" and r["results"][0]["score"] == 2.9
    assert seen["body"]["vectorQueries"][0]["fields"] == "embedding" and len(seen["body"]["vectorQueries"][0]["vector"]) == 256
    assert seen["body"]["queryType"] == "semantic" and "api-version=2024-07-01" in seen["url"]
    monkeypatch.setattr(httpx, "post", lambda *a, **k: Resp({}, 500))
    r = retrieval.search_policy("cochlear implant", 3)
    assert r["backend"].startswith("local_hybrid (azure_ai_search failed") and r["results"][0]["doc_id"] == "NCD-50.3"


def test_blob_failure_falls_back_to_local(monkeypatch, tmp_path):
    monkeypatch.setenv("AZURE_STORAGE_ACCOUNT_URL", "https://example.blob.core.windows.net")

    def boom():
        raise ConnectionError("no network in tests")

    monkeypatch.setattr(storage, "_blob_client", boom)
    r = storage.save_json("t.json", {"a": 1}, local_dir=tmp_path)
    assert r["backend"].startswith("local (azure_blob failed") and (tmp_path / "t.json").exists()


def test_azure_openai_provider(monkeypatch):
    monkeypatch.setenv("CG_LLM_PROVIDER", "azure")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://foundry.example.openai.azure.com/")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-only-key")
    llm = get_llm()
    assert type(llm).__name__ == "AzureChatOpenAI" and llm.deployment_name == "gpt-4o-mini" and llm.openai_api_version == "2024-10-21"
    assert llm.temperature == 0
    monkeypatch.setenv("AZURE_OPENAI_MODEL", "gpt-4o")
    with pytest.raises(RuntimeError, match="only runs gpt-4o-mini"):
        get_llm()
    monkeypatch.setenv("CG_LLM_PROVIDER", "other")
    with pytest.raises(ValueError):
        get_llm()
