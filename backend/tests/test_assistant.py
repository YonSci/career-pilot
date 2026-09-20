from career.config import settings
from career import assistant
from tests.conftest import signup_member
from tests.test_workflow import JOB, verified_profile


def test_assistant_unavailable_without_server_key(client, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "")
    r = client.post("/api/assistant/chat", json={"messages": [{"role": "user", "content": "How do I start?"}]})
    assert r.status_code == 200 and r.json()["available"] is False and "not available" in r.json()["reply"]
    assert client.get("/api/assistant/suggestions").json()["questions"]


def test_assistant_grounds_answers_and_uses_member_status(client, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "server-key")
    captured = {}

    class FakeResponses:
        def create(self, **kw):
            captured.update(kw)

            class R:
                output_text = "Go to Account and paste your OpenAI key."

            return R()

    class FakeClient:
        def __init__(self, **kw):
            self.responses = FakeResponses()

    monkeypatch.setattr(assistant, "OpenAI", FakeClient)
    from fastapi.testclient import TestClient
    from career.main import app

    anon = TestClient(app)
    r = anon.post("/api/assistant/chat", json={"messages": [{"role": "user", "content": "How do I start?"}]})
    assert r.status_code == 200 and "Account" in r.json()["reply"]
    assert "KNOWLEDGE" in captured["instructions"] and "This user's workspace status" not in captured["instructions"]
    assert captured["store"] is False and captured["input"][-1]["role"] == "user"
    member = signup_member(client)
    r = member.post("/api/assistant/chat", json={"messages": [{"role": "user", "content": "What next?"}]})
    assert r.status_code == 200
    assert "This user's workspace status" in captured["instructions"] and "openai key set: no" in captured["instructions"]
    # Conversation is trimmed and malformed turns are dropped.
    long = [{"role": "user", "content": "x" * 5000}] * 30
    r = anon.post("/api/assistant/chat", json={"messages": long})
    assert r.status_code == 422  # content too long for the schema
    assert len(assistant.clean_messages([{"role": "user", "content": "a"}] * 40)) == assistant.MAX_TURNS * 2


def test_assistant_is_rate_limited(client, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "")
    from fastapi.testclient import TestClient
    from career.main import app

    anon = TestClient(app)
    codes = [anon.post("/api/assistant/chat", json={"messages": [{"role": "user", "content": "hi"}]}).status_code for _ in range(31)]
    assert codes[:30] == [200] * 30 and codes[30] == 429


def test_public_stats_are_aggregate_and_anonymous(client):
    verified_profile(client)
    client.post("/api/jobs", json=JOB)
    from fastapi.testclient import TestClient
    from career.main import app

    anon = TestClient(app)
    s = anon.get("/api/public/stats").json()
    assert s["accounts"] == 1 and s["postings_screened"] >= 1
    assert set(s) == {"accounts", "postings_screened", "evaluated", "strong_matches", "applications_drafted", "sources"}
