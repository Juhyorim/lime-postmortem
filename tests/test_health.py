from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_ok():
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert "index_ready" in body


def test_health_does_not_leak_api_key(monkeypatch):
    res = client.get("/health")
    assert "LLM_API_KEY" not in res.text
