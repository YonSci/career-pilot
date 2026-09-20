"""Regression tests for the beta review: concurrency contexts, network policy,
session invalidation, bootstrap protection, mailbox timeouts, webhook linking."""

import time
import threading
import httpx
import pytest
from career.config import settings
from career.db import Session, User, Record
from career import auth as accounts
from career import sources
from tests.conftest import CSRF, signup_member
from tests.test_workflow import JOB, verified_profile


def test_concurrent_evaluations_each_get_their_own_context(client, monkeypatch):
    verified_profile(client)
    client.post("/api/sources", json={"kind": "greenhouse", "value": "example"})
    feed = [{**JOB, "title": f"Data Scientist {i}", "url": f"https://example.org/jobs/{i}"} for i in range(8)]
    monkeypatch.setattr("career.service.collect", lambda *a, **k: (feed, []))
    monkeypatch.setattr(settings, "openai_api_key", "fake-test-key")
    seen_threads = set()

    def slow_match(profile, job, prefs):
        from career.db import current_user_id

        seen_threads.add(threading.get_ident())
        assert current_user_id(), "user scope must be visible inside the worker"
        time.sleep(0.2)
        return {"score": 80, "summary": "ok", "requirements": [], "strengths": [], "gaps": [], "mode": "ai"}

    monkeypatch.setattr("career.service.match_job", slow_match)
    client.post("/api/scan")
    state = client.get("/api/state").json()
    run = state["runs"][0]
    assert run["status"] == "completed" and run["matched"] == 8, run
    assert not run.get("warnings"), run.get("warnings")
    assert all(j["match"] for j in state["jobs"])
    assert len(seen_threads) > 1, "evaluations should run on several threads"


def test_concurrent_email_extraction_uses_separate_contexts(monkeypatch):
    calls = []

    def slow_extract(text, posted=None):
        from career.db import current_user_id

        calls.append(current_user_id())
        time.sleep(0.1)
        return [{"title": text}]

    monkeypatch.setattr(sources, "extract_email_jobs", slow_extract)
    from career.db import user_scope

    with user_scope({"id": "u1", "email": "u@example.org", "role": "member", "plan": "beta", "openai_key": "k", "imap": None}):
        jobs = sources.extract_email_batch([(f"mail {i}", None) for i in range(6)])
    assert [j["title"] for j in jobs] == [f"mail {i}" for i in range(6)]
    assert calls and all(c == "u1" for c in calls)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/feed.xml",
        "http://localhost:8000/x",
        "http://10.0.0.5/jobs",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/",
        "http://0.0.0.0/",
        "ftp://example.org/feed",
        "http://user:pw@example.org/",
    ],
)
def test_private_and_odd_destinations_are_rejected(url, monkeypatch):
    monkeypatch.setattr(sources, "resolve_host", lambda host: ["93.184.216.34"] if host == "example.org" else [host])
    with pytest.raises(ValueError):
        sources.public_url(url)


def test_public_destination_and_dns_to_private_are_handled(monkeypatch):
    monkeypatch.setattr(sources, "resolve_host", lambda host: ["93.184.216.34"])
    assert sources.public_url("https://example.org/jobs") == "https://example.org/jobs"
    monkeypatch.setattr(sources, "resolve_host", lambda host: ["10.1.2.3"])
    with pytest.raises(ValueError, match="private"):
        sources.public_url("https://internal.example.org/jobs")


def test_page_fetch_checks_redirects_and_size(monkeypatch):
    monkeypatch.setattr(sources, "resolve_host", lambda host: ["93.184.216.34"] if host.endswith("example.org") else ["127.0.0.1"])
    hops = []

    def handler(request):
        hops.append(str(request.url))
        if str(request.url).endswith("/start"):
            return httpx.Response(302, headers={"location": "http://169.254.169.254/latest"})
        if str(request.url).endswith("/big"):
            return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html><main>" + b"x" * (sources.MAX_PAGE_BYTES + 10) + b"</main></html>")
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html><main>Hydrology role in Ethiopia with Python and GIS</main></html>")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    ctx = sources.Context(delay=0)
    with pytest.raises(ValueError, match="private"):
        ctx.fetch_page(client, "https://example.org/start")
    assert ctx.fetch_page(client, "https://example.org/ok").startswith("Hydrology")
    text = ctx.fetch_page(client, "https://example.org/big")
    assert text is not None and len(text) <= sources.MAX_PAGE_BYTES


def test_source_validation_rejects_private_targets(client, monkeypatch):
    monkeypatch.setattr(sources, "resolve_host", lambda host: ["127.0.0.1"])
    assert client.post("/api/sources", json={"kind": "rss", "value": "http://intranet.local/feed.xml"}).status_code == 422
    assert client.post("/api/sources/test", json={"kind": "page", "value": "http://10.0.0.1/careers"}).status_code == 422


def test_password_reset_and_change_invalidate_other_sessions(client):
    member = signup_member(client)
    me = member.get("/api/auth/me").json()
    client.post(f"/api/admin/users/{me['id']}/reset")
    assert member.get("/api/state").status_code == 401
    from fastapi.testclient import TestClient
    from career.main import app

    a = TestClient(app)
    b = TestClient(app)
    for c in (a, b):
        assert c.post("/api/auth/login", json={"email": "member@example.org", "password": "member-password-123"}, headers=CSRF).status_code == 401
    temp = client.post(f"/api/admin/users/{me['id']}/reset").json()["temporary_password"]
    for c in (a, b):
        assert c.post("/api/auth/login", json={"email": "member@example.org", "password": temp}, headers=CSRF).status_code == 200
    assert a.put("/api/account/password", json={"current": temp, "new": "brand-new-password"}, headers=CSRF).status_code == 200
    assert a.get("/api/state").status_code == 200, "the session that changed the password stays valid"
    assert b.get("/api/state").status_code == 401, "other sessions are signed out"


def test_gzip_pages_are_decoded_once(monkeypatch):
    import gzip

    body = b"<html><main>Hydrology role with Python and GIS in Ethiopia</main></html>"

    def handler(request):
        return httpx.Response(200, headers={"content-type": "text/html", "content-encoding": "gzip"}, content=gzip.compress(body))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    r = sources.safe_get(client, "https://example.org/gz")
    assert "content-encoding" not in {k.lower() for k in r.headers}
    assert "Hydrology role" in r.text
    assert sources.Context(delay=0).fetch_page(client, "https://example.org/gz").startswith("Hydrology")


def test_imap_hosts_follow_the_destination_policy(monkeypatch):
    with pytest.raises(ValueError):
        sources.public_host("127.0.0.1")
    with pytest.raises(ValueError):
        sources.public_host("mail.internal")
    monkeypatch.setattr(sources, "resolve_host", lambda host: ["10.0.0.9"])
    with pytest.raises(ValueError, match="private"):
        sources.imap_check({"host": "imap.example.org", "username": "u", "password": "p"})
    monkeypatch.setattr(sources, "resolve_host", lambda host: ["93.184.216.34"])
    assert sources.public_host("imap.example.org") == "93.184.216.34"


def test_imap_connection_is_pinned_to_the_validated_address(monkeypatch):
    seen = {}

    class FakeBox:
        def __init__(self, host, port, timeout=None):
            seen.update(host=host, port=port, timeout=timeout)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def login(self, u, p):
            return "OK", []

        def select(self, folder, readonly=True):
            return "OK", [b"5"]

    monkeypatch.setattr(sources.imaplib, "IMAP4_SSL", FakeBox)
    assert sources.imap_check({"host": "imap.example.org", "username": "u", "password": "p", "folder": "CareerPilot"}) == 5
    assert seen == {"host": "imap.example.org", "port": 993, "timeout": sources.IMAP_TIMEOUT}
    # The pinned subclass overrides socket creation with the validated address.
    box = sources.imap_connect("imap.example.org", 993)
    assert type(box).__name__ == "PinnedIMAP4_SSL" and "_create_socket" in type(box).__dict__


def test_pro_plus_can_be_assigned(client):
    member = signup_member(client)
    me = member.get("/api/auth/me").json()
    r = client.put(f"/api/admin/users/{me['id']}", json={"plan": "pro_plus"})
    assert r.status_code == 200 and r.json()["plan"] == "pro_plus"
    assert member.get("/api/state").json()["plan"]["packages_per_month"] == 30


def test_alert_resend_only_for_unknown_delivery(client, monkeypatch):
    verified_profile(client)
    job = client.post("/api/jobs", json=JOB).json()
    from career.db import Session, put
    from tests.conftest import OWNER

    with Session() as db:
        owner = db.query(User).filter_by(email=OWNER["email"]).one()
        put(db, "job", "job:x", {**JOB, "status": "new", "match": {"score": 90, "mode": "ai", "summary": "s", "requirements": [], "strengths": [], "gaps": []}}, user_id=owner.id)
        row = put(db, "alert", f"alert:{job['id']}:telegram", {"job_id": job["id"], "channel": "telegram", "status": "accepted"}, user_id=owner.id)
        unknown = put(db, "alert", f"alert:{job['id']}:email", {"job_id": job["id"], "channel": "email", "status": "delivery_unknown"}, user_id=owner.id)
        ok_id, unknown_id = row.id, unknown.id
    assert client.post(f"/api/alerts/{ok_id}/resend").status_code == 422
    client.post(f"/api/jobs/{job['id']}/match")  # keyword match so the job has an evaluation
    sent = []
    monkeypatch.setattr("career.notifications.send_alert", lambda *a, **k: sent.append(a))
    r = client.post(f"/api/alerts/{unknown_id}/resend")
    assert r.status_code == 200 and r.json()["status"] == "accepted" and len(sent) == 1


def test_first_account_requires_setup_code_or_owner_email(monkeypatch):
    from fastapi.testclient import TestClient
    from career.main import app
    from tests.conftest import reset_database

    with TestClient(app) as anon:
        reset_database()
        assert anon.get("/api/setup").json()["needs_first_account"] is True
        r = anon.post("/api/auth/signup", json={"email": "x@example.org", "password": "long-enough-pw"}, headers=CSRF)
        assert r.status_code == 422 and "setup code" in r.json()["detail"].lower()
        r = anon.post("/api/auth/signup", json={"email": "x@example.org", "password": "long-enough-pw", "invite": "wrong"}, headers=CSRF)
        assert r.status_code == 422
        r = anon.post("/api/auth/signup", json={"email": "x@example.org", "password": "long-enough-pw", "invite": settings.app_token}, headers=CSRF)
        assert r.status_code == 200 and r.json()["role"] == "admin"
    with TestClient(app) as anon:
        reset_database()
        monkeypatch.setattr(settings, "owner_email", "owner@example.org")
        # The email restriction never replaces the setup code.
        assert anon.post("/api/auth/signup", json={"email": "Owner@Example.org", "password": "long-enough-pw"}, headers=CSRF).status_code == 422
        assert anon.post("/api/auth/signup", json={"email": "other@example.org", "password": "long-enough-pw", "invite": settings.app_token}, headers=CSRF).status_code == 422
        assert anon.post("/api/auth/signup", json={"email": "Owner@Example.org", "password": "long-enough-pw", "invite": settings.app_token}, headers=CSRF).status_code == 200


def test_imap_connections_have_a_timeout(monkeypatch):
    seen = {}

    class FakeBox:
        def __init__(self, host, port, timeout=None):
            seen["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def login(self, u, p):
            return "OK", []

        def select(self, folder, readonly=True):
            return "OK", [b"3"]

    monkeypatch.setattr(sources.imaplib, "IMAP4_SSL", FakeBox)
    assert sources.imap_check({"host": "imap.example.org", "username": "u", "password": "p", "folder": "CareerPilot"}) == 3
    assert seen["timeout"] and seen["timeout"] <= 60


def test_webhook_handles_linking_messages(client, monkeypatch):
    from career import telegram

    sent = []
    monkeypatch.setattr(telegram, "api", lambda method, **p: sent.append((method, p)) or {})
    monkeypatch.setattr(settings, "telegram_webhook_secret", "secret")
    monkeypatch.setattr(settings, "telegram_bot_token", "token")
    monkeypatch.setattr(telegram, "bot_username", lambda: "bot")
    code = client.post("/api/telegram/link").json()["code"]
    payload = {"message": {"chat": {"id": 4242, "type": "private"}, "from": {"username": "owner"}, "text": "/start " + code}}
    r = client.post("/api/telegram/webhook", json=payload, headers={"X-Telegram-Bot-Api-Secret-Token": "secret"})
    assert r.status_code == 200
    assert client.get("/api/state").json()["telegram"]["linked"] is True
    assert sent and sent[-1][0] == "sendMessage"
