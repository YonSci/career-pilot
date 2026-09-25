"""Owner invites waitlist requests: personal code, email with the sign-up link, waitlist marked."""

from fastapi.testclient import TestClient
from career.config import settings
from career.main import app
from career import notifications
from tests.conftest import signup_member, CSRF


def test_invite_waitlist_requests(client, monkeypatch):
    sent = []
    monkeypatch.setattr(notifications, "email_send", lambda subject, text, to=None: sent.append((subject, text, to)))
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.org")
    monkeypatch.setattr(settings, "email_from", "owner@example.org")
    monkeypatch.setattr(settings, "public_url", "https://jobs.example.org")
    anon = TestClient(app)
    assert anon.post("/api/waitlist", json={"email": "Ada@Example.org", "name": "Ada Lovelace", "note": "GIS"}, headers=CSRF).status_code == 200
    r = client.post("/api/admin/waitlist/invite", json={"emails": ["ada@example.org", "new.person@example.org", "not-an-email"]})
    assert r.status_code == 200, r.text
    results = {x["email"]: x for x in r.json()["results"]}
    assert results["ada@example.org"]["status"] == "sent" and results["new.person@example.org"]["status"] == "sent" and results["not-an-email"]["status"] == "invalid"
    code = results["ada@example.org"]["code"]
    assert len(sent) == 2
    subject, text, to = sent[0]
    assert to == "ada@example.org" and "Hello Ada," in text and f"https://jobs.example.org/app/?invite={code}" in text and "do not forward" in text
    overview = client.get("/api/admin/overview").json()
    entry = next(w for w in overview["waitlist"] if w["email"] == "ada@example.org")
    assert entry["invited"] and entry["code"] == code
    assert any(w["email"] == "new.person@example.org" and w["invited"] for w in overview["waitlist"])
    assert any(i["code"] == code and i["note"] == "ada@example.org" for i in overview["invites"])
    # Resending reuses the same code; the code works for sign-up; a registered address is skipped.
    r2 = client.post("/api/admin/waitlist/invite", json={"emails": ["ada@example.org"]}).json()["results"][0]
    assert r2["code"] == code and len(sent) == 3
    ada = TestClient(app)
    assert ada.post("/api/auth/signup", json={"email": "ada@example.org", "password": "ada-password-123", "invite": code}, headers=CSRF).status_code == 200
    assert client.post("/api/admin/waitlist/invite", json={"emails": ["ada@example.org"]}).json()["results"][0]["status"] == "already_registered"


def test_invite_without_email_returns_code_and_members_are_forbidden(client, monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "")
    r = client.post("/api/admin/waitlist/invite", json={"emails": ["someone@example.org"]}).json()
    assert r["email_configured"] is False and r["results"][0]["status"] == "code_only" and r["results"][0]["link"].endswith("/app/?invite=" + r["results"][0]["code"])
    member = signup_member(client)
    assert member.post("/api/admin/waitlist/invite", json={"emails": ["x@example.org"]}).status_code == 403
