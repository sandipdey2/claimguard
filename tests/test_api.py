from fastapi.testclient import TestClient

from api.main import app
from tests.conftest import FakeLLM


def test_health_and_auth(monkeypatch):
    monkeypatch.delenv("CG_API_ALLOW_ANON", raising=False)
    monkeypatch.setenv("CG_API_KEY", "test-key-123")
    c = TestClient(app)
    h = c.get("/health").json()
    assert h["status"] == "ok" and h["azure_adapters"]["ai_search"] is False
    assert c.get("/v1/cases").status_code == 401
    assert c.get("/v1/cases", headers={"X-API-Key": "test-key-123"}).status_code == 200


def test_appeal_signoff_and_verify(monkeypatch):
    monkeypatch.setenv("CG_API_ALLOW_ANON", "1")
    app.state.llm_factory = FakeLLM
    c = TestClient(app)
    r = c.post("/v1/appeals", json={"reference_id": "MN25-45854"}).json()
    assert r["status"] == "awaiting_human_signoff"
    s = c.post(f"/v1/appeals/{r['run_id']}/signoff", json={"reviewer": "Billing lead", "approved": True}).json()
    assert s["status"] == "released"
    assert c.post("/v1/receipts/verify", json=s["receipt"]).json()["valid"] is True
    assert c.post(f"/v1/appeals/{r['run_id']}/signoff", json={"reviewer": "x", "approved": True}).status_code == 409
    assert c.post("/v1/appeals", json={"reference_id": "XX00-1"}).status_code == 404
    app.state.llm_factory = None
