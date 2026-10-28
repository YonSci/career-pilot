"""Joining without a code while open places last, and one-tap Telegram linking."""

from fastapi.testclient import TestClient
from career import telegram
from career.config import settings
from career.db import Session, read
from career.main import app
from tests.conftest import CSRF, signup_member


def join(email, invite=""):
    return TestClient(app).post("/api/auth/signup", json={"email": email, "password": "long-enough-pw", "invite": invite}, headers=CSRF)


def test_open_places_let_people_join_without_a_code_up_to_the_daily_limit(client, monkeypatch):
    monkeypatch.setattr(settings, "open_seats_per_day", 2)
    anon = TestClient(app)
    assert anon.get("/api/setup").json()["open_seats_left"] == 2
    r = anon.post("/api/waitlist", json={"email": "ada@example.org", "name": "Ada", "note": "GIS"}, headers=CSRF).json()
    assert r == {"ok": True, "join_now": True, "registered": False}
    assert join("ada@example.org").status_code == 200
    # A wrong code is an error, not a silent open place, so referral credit is never lost.
    wrong = join("bo@example.org", "not-a-code")
    assert wrong.status_code == 422 and "Leave the field empty" in wrong.json()["detail"]
    assert join("bo@example.org").status_code == 200
    assert anon.get("/api/setup").json()["open_seats_left"] == 0
    full = join("cy@example.org")
    assert full.status_code == 422 and "open places are taken" in full.json()["detail"]
    assert anon.post("/api/waitlist", json={"email": "cy@example.org"}, headers=CSRF).json()["join_now"] is False
    assert anon.post("/api/waitlist", json={"email": "ada@example.org"}, headers=CSRF).json()["registered"] is True
    # Codes still work when the open places are gone; open places are visible to the owner.
    code = client.post("/api/admin/invites", json={"count": 1}).json()["codes"][0]
    assert join("cy@example.org", code).status_code == 200
    notes = [i["note"] for i in client.get("/api/admin/overview").json()["invites"] if i["used_by"]]
    assert sorted(n for n in notes if n.startswith("open:")) == ["open:ada@example.org", "open:bo@example.org"]


def test_telegram_deep_link_and_start_replies(client, monkeypatch):
    sent = []
    monkeypatch.setattr(telegram, "api", lambda method, **p: sent.append(p) or {})
    monkeypatch.setattr(telegram, "bot_username", lambda: "jobsbot")
    monkeypatch.setattr(settings, "telegram_bot_token", "token")
    member = signup_member(client)
    r = member.post("/api/telegram/link").json()
    assert r["link"] == f"https://t.me/jobsbot?start={r['code']}"
    assert member.get("/api/telegram/link").json()["linked"] is False
    with Session() as db:
        # Pressing Start in a chat nobody linked: a pointer to sign-up, nothing else.
        telegram.handle_message(db, {"chat": {"id": 1, "type": "private"}, "from": {}, "text": "/start"})
        assert "create a free account" in sent[-1]["text"] and "/app/?join=1" in sent[-1]["text"]
        telegram.handle_message(db, {"chat": {"id": 1, "type": "private"}, "from": {}, "text": "/start ABC123"})
        assert "expired" in sent[-1]["text"]
        before = len(sent)
        telegram.handle_message(db, {"chat": {"id": 1, "type": "private"}, "from": {}, "text": "hello"})
        assert len(sent) == before  # other messages from strangers stay unanswered
        # The deep link sends "/start CODE": that links the member's chat.
        telegram.handle_message(db, {"chat": {"id": 2, "type": "private"}, "from": {"username": "m"}, "text": "/start " + r["code"]})
        assert sent[-1]["text"].startswith("Linked.")
    assert member.get("/api/telegram/link").json()["linked"] is True
