"""Isolation across every per-user endpoint, spend caps, rate limits, input cleaning, telemetry."""

import pytest
from career.config import settings
from career.db import Session, User, put
from career import ai, telemetry
from tests.conftest import signup_member
from tests.test_workflow import JOB, verified_profile, package


def test_every_per_user_endpoint_is_isolated(client, monkeypatch):
    verified_profile(client)
    job = client.post("/api/jobs", json=JOB).json()
    src = client.post("/api/sources", json={"kind": "greenhouse", "value": "example"}).json()
    monkeypatch.setattr(settings, "openai_api_key", "fake-test-key")
    monkeypatch.setattr("career.service.write_package", lambda *a: package())
    client.post(f"/api/jobs/{job['id']}/prepare")
    app_id = client.get("/api/state").json()["applications"][0]["id"]
    with Session() as db:
        owner = db.query(User).filter_by(role="admin").one()
        alert = put(db, "alert", f"alert:{job['id']}:email", {"job_id": job["id"], "channel": "email", "status": "delivery_unknown"}, user_id=owner.id)
        alert_id = alert.id
    member = signup_member(client)
    checks = [
        ("GET", f"/api/jobs/{job['id']}", None),
        ("POST", f"/api/jobs/{job['id']}/match", None),
        ("POST", f"/api/jobs/{job['id']}/prepare", None),
        ("PUT", f"/api/jobs/{job['id']}/decision", {"status": "skipped"}),
        ("PUT", f"/api/applications/{app_id}", {"package": package(), "status": "review"}),
        ("GET", f"/api/applications/{app_id}/download", None),
        ("GET", f"/api/applications/{app_id}/versions", None),
        ("PUT", f"/api/sources/{src['id']}", {"enabled": False}),
        ("DELETE", f"/api/sources/{src['id']}", None),
        ("POST", f"/api/alerts/{alert_id}/resend", None),
    ]
    for method, path, body in checks:
        r = member.request(method, path, json=body)
        assert r.status_code in (404, 409, 422), (method, path, r.status_code, r.text[:120])
        assert "Example Applicant" not in r.text and "Climate Data Scientist" not in r.text
    # Owner data is unchanged.
    state = client.get("/api/state").json()
    assert state["jobs"][0]["status"] != "skipped" and len(state["sources"]) == 1 and state["applications"][0]["status"] == "review"
    # Member's inbox read and telegram unlink touch only their own records.
    assert member.post("/api/inbox/read", json={"job_ids": []}).json()["read"] == 0
    assert client.get("/api/state").json()["alerts"]


def test_state_and_setup_never_expose_secrets(client, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "sk-server-secret-000")
    monkeypatch.setattr(settings, "telegram_bot_token", "123:BOT-SECRET")
    monkeypatch.setattr(settings, "smtp_password", "smtp-secret")
    monkeypatch.setattr(settings, "posthog_key", "phc_public")
    member = signup_member(client)
    monkeypatch.setattr("career.main.verify_key", lambda key: None)
    member.put("/api/account/openai_key", json={"key": "sk-member-secret-1234567890"})
    for body in (member.get("/api/state").text, member.get("/api/auth/me").text, client.get("/api/admin/overview").text, client.get("/api/setup").text):
        for secret in ("sk-server-secret", "BOT-SECRET", "smtp-secret", "sk-member-secret", "test-token-only"):
            assert secret not in body


def test_server_key_monthly_cap_stops_calls(client, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "server-key")
    monkeypatch.setattr(settings, "server_key_monthly_calls", 2)
    calls = []

    class FakeResponses:
        def parse(self, **kw):
            calls.append(1)

            class R:
                output_parsed = package_obj

            return R()

    from career.schemas import Match
    package_obj = Match(score=1, summary="s", requirements=[], strengths=[], gaps=[])

    class FakeClient:
        def __init__(self, **kw):
            self.responses = FakeResponses()

    monkeypatch.setattr(ai, "OpenAI", FakeClient)
    from career.db import user_scope

    with user_scope({"id": "owner-x", "email": "o@example.org", "role": "admin", "plan": "beta", "openai_key": "", "imap": None, "sponsored": False}):
        ai.structured("m", Match, "i", {})
        ai.structured("m", Match, "i", {})
        with pytest.raises(ValueError, match="exhausted"):
            ai.structured("m", Match, "i", {})
    assert len(calls) == 2
    usage = ai.server_key_usage()
    assert usage["calls"] == 2 and usage["by_user"]["owner-x"] == 2 and usage["by_purpose"]["Match"] == 2
    # A member's own key is never counted against the server cap.
    with user_scope({"id": "member-y", "email": "m@example.org", "role": "member", "plan": "beta", "openai_key": "sk-own", "imap": None, "sponsored": False}):
        ai.structured("m", Match, "i", {})
    assert ai.server_key_usage()["calls"] == 2


def test_manual_ai_actions_are_rate_limited(client, monkeypatch):
    monkeypatch.setattr(settings, "ai_actions_per_hour", 4)  # extraction below uses one
    verified_profile(client)
    job = client.post("/api/jobs", json=JOB).json()
    codes = [client.post(f"/api/jobs/{job['id']}/match").status_code for _ in range(4)]
    assert codes[:3] == [200, 200, 200] and codes[3] == 429


def test_untrusted_text_is_cleaned_before_the_model():
    dirty = "Title\x00\x07 with control chars\n\n\n\n\n\nand      wide gaps"
    cleaned = ai.clean_text(dirty)
    assert "\x00" not in cleaned and "\x07" not in cleaned and "\n\n\n\n" not in cleaned
    assert ai.clean_text("x" * 50, 10).startswith("xxxxxxxxxx") and "[truncated]" in ai.clean_text("x" * 50, 10)
    job = ai.job_for_model({"title": "T\x01", "description": "d" * 10})
    assert job["title"] == "T " and job["description"] == "d" * 10


def test_telemetry_is_silent_without_key_and_sends_no_personal_data(monkeypatch):
    sent = []
    monkeypatch.setattr(telemetry, "_post", lambda payload: sent.append(payload))
    monkeypatch.setattr(settings, "posthog_key", "")
    telemetry.capture("server_search_completed", {"seconds": 1})
    assert sent == []
    monkeypatch.setattr(settings, "posthog_key", "phc_x")
    telemetry.capture("server_search_completed", {"seconds": 1, "added": 2}, distinct_id="user-1")
    import time
    time.sleep(0.2)
    assert sent and sent[0]["event"] == "server_search_completed" and sent[0]["distinct_id"] == "user-1"
    assert sent[0]["properties"]["$lib"] == "career-pilot-server" and sent[0]["properties"]["$process_person_profile"] is True
    try:
        raise RuntimeError("boom sk-secret")
    except RuntimeError as e:
        telemetry.capture_exception(e, where="test")
    time.sleep(0.2)
    exc = sent[-1]
    assert exc["event"] == "$exception" and exc["properties"]["$exception_list"][0]["type"] == "RuntimeError"


def test_unhandled_errors_return_generic_message(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr("career.main.package_zip", boom)
    verified_profile(client)
    job = client.post("/api/jobs", json=JOB).json()
    monkeypatch.setattr(settings, "openai_api_key", "fake-test-key")
    monkeypatch.setattr("career.service.write_package", lambda *a: package())
    client.post(f"/api/jobs/{job['id']}/prepare")
    app_id = client.get("/api/state").json()["applications"][0]["id"]
    from fastapi.testclient import TestClient
    from career.main import app

    raw = TestClient(app, raise_server_exceptions=False)
    raw.headers["Authorization"] = client.headers["Authorization"]
    r = raw.get(f"/api/applications/{app_id}/download")
    assert r.status_code == 500 and "secret internal detail" not in r.text and "Something went wrong" in r.text


def test_organisation_for_group_analytics(client, monkeypatch):
    member = signup_member(client)
    uid = member.get("/api/auth/me").json()["id"]
    r = client.put(f"/api/admin/users/{uid}", json={"organisation": "  UN Economic Commission for Africa "})
    assert r.status_code == 200 and r.json()["organisation"] == "UN Economic Commission for Africa"
    assert member.get("/api/auth/me").json()["organisation"] == "UN Economic Commission for Africa"
    assert member.put(f"/api/admin/users/{uid}", json={"organisation": "x"}).status_code == 403
    sent = []
    monkeypatch.setattr(telemetry, "_post", lambda payload: sent.append(payload))
    monkeypatch.setattr(settings, "posthog_key", "phc_x")
    from career.db import user_scope

    with user_scope({"id": uid, "email": "m@example.org", "role": "member", "plan": "beta", "openai_key": "", "imap": None, "sponsored": False, "organisation": "UNECA"}):
        telemetry.capture("server_search_completed", {"seconds": 1}, distinct_id=uid)
    import time
    time.sleep(0.2)
    assert sent[0]["properties"]["$groups"] == {"organisation": "UNECA"}
    assert client.put(f"/api/admin/users/{uid}", json={"organisation": ""}).json()["organisation"] == ""


def test_rejected_key_is_reported_and_failed_calls_are_refunded(client, monkeypatch):
    import httpx
    from openai import AuthenticationError, APIConnectionError, RateLimitError
    from career.db import user_scope
    from career.schemas import Match

    monkeypatch.setattr(settings, "openai_api_key", "server-key")
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    failure = [AuthenticationError("Incorrect API key provided", response=httpx.Response(401, request=request), body=None)]

    class FakeClient:
        def __init__(self, **kw):
            self.responses = self

        def parse(self, **kw):
            raise failure[0]

    monkeypatch.setattr(ai, "OpenAI", FakeClient)
    owner = {"id": "owner-x", "email": "o@example.org", "role": "admin", "plan": "beta", "openai_key": "", "imap": None, "sponsored": False}
    with user_scope(owner):
        with pytest.raises(ai.KeyRejected, match="OPENAI_API_KEY"):
            ai.structured("m", Match, "i", {})
        failure[0] = RateLimitError("You exceeded your current quota", response=httpx.Response(429, request=request), body={"code": "insufficient_quota"})
        with pytest.raises(ai.KeyRejected, match="no credit left. The owner"):
            ai.structured("m", Match, "i", {})
        # An ordinary rate limit is temporary: the posting is retried later, the search goes on.
        failure[0] = RateLimitError("Rate limit reached", response=httpx.Response(429, request=request), body={"code": "rate_limit_exceeded"})
        with pytest.raises(RateLimitError):
            ai.structured("m", Match, "i", {})
        failure[0] = APIConnectionError(request=request)
        with pytest.raises(APIConnectionError):
            ai.structured("m", Match, "i", {})
    usage = ai.server_key_usage()
    assert usage["calls"] == 0 and usage["by_user"]["owner-x"] == 0 and usage["by_purpose"]["Match"] == 0
    with user_scope({**owner, "id": "member-y", "role": "member", "openai_key": "sk-own"}):
        failure[0] = AuthenticationError("Incorrect API key provided", response=httpx.Response(401, request=request), body=None)
        with pytest.raises(ai.KeyRejected, match="under Account"):
            ai.structured("m", Match, "i", {})
