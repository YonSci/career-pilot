from career.db import Session, User, Record, read, put, user_scope, user_snapshot
from career.config import settings
from career import auth as accounts
from tests.conftest import OWNER, CSRF, signup_member
from tests.test_workflow import JOB, verified_profile


def test_first_account_is_owner_and_claims_legacy_records(client):
    me = client.get("/api/auth/me").json()
    assert me["role"] == "admin" and me["plan"] == "beta"
    assert client.get("/api/setup").json()["needs_first_account"] is False
    # Records without an owner (pre-account data) belong to the first admin.
    with Session() as db:
        put(db, "job", "job:legacy", {"title": "Legacy", "status": "new", "description": "x"}, user_id="")
        owner = db.query(User).filter_by(role="admin").one()
        assert accounts.claim_legacy_records(db, owner) == 1
    assert any(j["title"] == "Legacy" for j in client.get("/api/state").json()["jobs"])


def test_signup_requires_invite_and_login_sets_cookie(client):
    from fastapi.testclient import TestClient
    from career.main import app

    anon = TestClient(app)
    r = anon.post("/api/auth/signup", json={"email": "x@example.org", "password": "long-enough-pw"}, headers=CSRF)
    assert r.status_code == 422 and "invite" in r.json()["detail"]
    assert anon.get("/api/state").status_code == 401
    member = signup_member(client)
    assert member.get("/api/auth/me").json()["role"] == "member"
    # Invite codes are single use.
    used = client.get("/api/admin/overview").json()["invites"][0]
    assert used["used_by"]
    again = TestClient(app)
    assert again.post("/api/auth/signup", json={"email": "y@example.org", "password": "long-enough-pw", "invite": used["code"]}, headers=CSRF).status_code == 422
    # Login, CSRF header, logout.
    fresh = TestClient(app)
    assert fresh.post("/api/auth/login", json={"email": "member@example.org", "password": "wrong-password-1"}, headers=CSRF).status_code == 401
    assert fresh.post("/api/auth/login", json={"email": "member@example.org", "password": "member-password-123"}, headers=CSRF).status_code == 200
    assert fresh.get("/api/state").status_code == 200
    assert fresh.post("/api/scan").status_code == 403  # missing X-Requested-With
    assert fresh.post("/api/auth/logout", headers=CSRF).status_code == 200
    assert fresh.get("/api/state").status_code == 401


def test_users_are_isolated(client):
    verified_profile(client)
    owner_job = client.post("/api/jobs", json=JOB).json()
    member = signup_member(client)
    assert member.get("/api/state").json()["jobs"] == []
    assert member.get("/api/state").json()["profile"]["facts"] == []
    assert member.get(f"/api/jobs/{owner_job['id']}").status_code == 404
    assert member.put(f"/api/jobs/{owner_job['id']}/decision", json={"status": "skipped"}).status_code == 404
    member_job = member.post("/api/jobs", json={**JOB, "url": "https://example.org/jobs/member"}).json()
    assert member_job["created_new"] and len(member.get("/api/state").json()["jobs"]) == 1
    assert len(client.get("/api/state").json()["jobs"]) == 1
    # Same natural key ("profile") may exist for both users.
    member.put("/api/profile", json={"name": "Member", "headline": "", "facts": []})
    assert client.get("/api/state").json()["profile"]["name"] == "Example Applicant"
    assert member.get("/api/admin/overview").status_code == 403


def test_member_needs_own_openai_key(client, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "server-key")
    member = signup_member(client)
    assert member.get("/api/state").json()["connections"]["ai"] is False
    assert client.get("/api/state").json()["connections"]["ai"] is True  # owner uses the server key
    monkeypatch.setattr("career.main.verify_key", lambda key: None)
    r = member.put("/api/account/openai_key", json={"key": "sk-test-1234567890abcdefghij"})
    assert r.status_code == 200 and r.json()["has_openai_key"]
    state = member.get("/api/state").json()
    assert state["connections"]["ai"] and state["connections"]["ai_own_key"]
    # The stored key is encrypted at rest and decrypts to the original.
    with Session() as db:
        user = db.query(User).filter_by(email="member@example.org").one()
        assert "sk-test" not in user.secrets["openai_key"]
        assert user_snapshot(user)["openai_key"] == "sk-test-1234567890abcdefghij"
    assert member.delete("/api/account/openai_key").json()["has_openai_key"] is False


def test_plan_limits_are_enforced(client):
    member = signup_member(client)
    me = member.get("/api/auth/me").json()
    assert client.put(f"/api/admin/users/{me['id']}", json={"plan": "free"}).json()["plan"] == "free"
    assert member.put("/api/schedule", json={"enabled": True}).status_code == 403
    assert member.post("/api/sources", json={"kind": "greenhouse", "value": "a"}).status_code == 200
    assert member.post("/api/sources", json={"kind": "greenhouse", "value": "b"}).status_code == 200
    assert member.post("/api/sources", json={"kind": "greenhouse", "value": "c"}).status_code == 403
    assert member.get("/api/state").json()["plan"]["sources"] == 2


def test_admin_overview_reports_activation(client):
    verified_profile(client)
    client.post("/api/sources", json={"kind": "greenhouse", "value": "example"})
    signup_member(client)
    overview = client.get("/api/admin/overview").json()
    assert overview["totals"]["users"] == 2 and overview["totals"]["activated"] == 1
    owner = next(u for u in overview["users"] if u["email"] == OWNER["email"])
    assert owner["verified_facts"] == 3 and owner["sources"] == 1 and owner["activated"] and not owner["drafted"]


def test_password_change_and_admin_reset(client):
    member = signup_member(client)
    assert member.put("/api/account/password", json={"current": "nope", "new": "another-long-pw"}).status_code == 422
    assert member.put("/api/account/password", json={"current": "member-password-123", "new": "another-long-pw"}).status_code == 200
    me = member.get("/api/auth/me").json()
    temp = client.post(f"/api/admin/users/{me['id']}/reset").json()["temporary_password"]
    from fastapi.testclient import TestClient
    from career.main import app

    fresh = TestClient(app)
    assert fresh.post("/api/auth/login", json={"email": "member@example.org", "password": temp}, headers=CSRF).status_code == 200


def test_imap_credentials_are_checked_and_sealed(client, monkeypatch):
    member = signup_member(client)
    monkeypatch.setattr("career.main.imap_check", lambda creds: 12)
    r = member.put("/api/account/imap", json={"host": "imap.gmail.com", "username": "m@gmail.com", "password": "app-pass", "folder": "CareerPilot"})
    assert r.status_code == 200 and r.json()["has_imap"] and r.json()["messages_in_folder"] == 12
    assert member.get("/api/state").json()["connections"]["imap"] is True
    # The imap source can now be added; the Gmail OAuth source is owner-only.
    assert member.post("/api/sources", json={"kind": "imap", "value": ""}).status_code == 200
    with Session() as db:
        user = db.query(User).filter_by(email="member@example.org").one()
        assert "app-pass" not in str(user.secrets)


def test_telegram_linking_is_per_user(client, monkeypatch):
    from career import telegram

    sent = []
    monkeypatch.setattr(telegram, "api", lambda method, **p: sent.append((method, p)) or {})
    monkeypatch.setattr(settings, "telegram_bot_token", "token")
    monkeypatch.setattr(telegram, "bot_username", lambda: "bot")
    member = signup_member(client)
    code = member.post("/api/telegram/link").json()["code"]
    with Session() as db:
        telegram.handle_message(db, {"chat": {"id": 4242, "type": "private"}, "from": {"username": "m"}, "text": code})
    assert member.get("/api/state").json()["telegram"]["linked"] is True
    assert client.get("/api/state").json()["telegram"]["linked"] is False
    # A button press from that chat only changes the member's jobs.
    owner_job = client.post("/api/jobs", json=JOB).json()
    member_job = member.post("/api/jobs", json={**JOB, "url": "https://example.org/jobs/m"}).json()
    with Session() as db:
        telegram.handle_callback(db, {"id": "1", "from": {"id": 4242}, "message": {"chat": {"id": 4242}}, "data": "save:" + owner_job["id"]})
        telegram.handle_callback(db, {"id": "2", "from": {"id": 4242}, "message": {"chat": {"id": 4242}}, "data": "save:" + member_job["id"]})
    assert client.get(f"/api/jobs/{owner_job['id']}").json()["status"] == "new"
    assert member.get(f"/api/jobs/{member_job['id']}").json()["status"] == "saved"


def test_scheduler_walks_due_accounts(client, monkeypatch):
    from career import scheduler

    member = signup_member(client)
    member.put("/api/schedule", json={"enabled": True})
    due = scheduler.due_users()
    assert [u["email"] for u in due] == ["member@example.org"]
    ran = []
    monkeypatch.setattr(scheduler, "run_scan", lambda run_id, user_id: ran.append(user_id))
    for user in due:
        scheduler.scheduled_scan(user)
    assert len(ran) == 1
    assert member.get("/api/state").json()["runs"][0]["trigger"] == "scheduled"
    assert client.get("/api/state").json()["runs"] == []
