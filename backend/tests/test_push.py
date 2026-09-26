"""Web push: subscription storage, availability, alerts through push, dead-subscription cleanup, setup exposure."""

from fastapi.testclient import TestClient
from career.config import settings
from career.db import Session, User, user_scope, user_snapshot
from career.main import app
from career import notifications
from tests.conftest import signup_member

SUB = {"endpoint": "https://push.example.org/send/abc", "keys": {"p256dh": "BPx" + "a" * 60, "auth": "auth123"}}


def test_subscribe_send_and_cleanup(client, monkeypatch):
    monkeypatch.setattr(settings, "vapid_public_key", "pub")
    monkeypatch.setattr(settings, "vapid_private_key", "priv")
    monkeypatch.setattr(settings, "vapid_subject", "mailto:owner@example.org")
    assert TestClient(app).get("/api/setup").json()["vapid_public_key"] == "pub"
    member = signup_member(client)
    assert member.put("/api/account/push", json={"subscription": {"endpoint": "http://insecure", "keys": {}}}).status_code == 422
    r = member.put("/api/account/push", json={"subscription": SUB, "label": "Chrome on Android"})
    assert r.status_code == 200 and r.json()["devices"] == 1
    state = member.get("/api/state").json()
    assert state["user"]["has_push"] and state["connections"]["push"] and "push" in state["preferences"]["notify_channels"]
    # Same endpoint again replaces rather than duplicates; a second device adds.
    member.put("/api/account/push", json={"subscription": SUB})
    assert member.put("/api/account/push", json={"subscription": {**SUB, "endpoint": "https://push.example.org/send/def"}}).json()["devices"] == 2
    # The stored subscriptions are sealed, never in plain text.
    with Session() as db:
        u = db.query(User).filter_by(email="member@example.org").one()
        assert "push.example.org" not in str(u.secrets)
        snap = user_snapshot(u)
    calls = []

    class FakeResp:
        def __init__(self, code):
            self.status_code = code

    from pywebpush import WebPushException

    def fake_webpush(subscription_info, data, vapid_private_key, vapid_claims, ttl):
        calls.append((subscription_info["endpoint"], data, vapid_claims["sub"]))
        if subscription_info["endpoint"].endswith("/abc"):
            raise WebPushException("gone", response=FakeResp(410))
        return True

    monkeypatch.setattr("pywebpush.webpush", fake_webpush)
    with user_scope(snap):
        assert notifications.availability()["push"]
        notifications.send_alert("push", {"title": "Hydrologist", "company": "Water Org", "location": "Kenya", "url": ""}, {"score": 88, "summary": "Strong"}, "job1")
    assert len(calls) == 2 and calls[0][2] == "mailto:owner@example.org" and '"88/100 \\u00b7 Hydrologist"' in calls[0][1] and "Water Org" in calls[1][1]
    # The 410 subscription was dropped; the other stays.
    with Session() as db:
        u = db.query(User).filter_by(email="member@example.org").one()
        from career.auth import unseal

        left = unseal(u.secrets["push"])
        assert len(left) == 1 and left[0]["subscription"]["endpoint"].endswith("/def")
    # Test alert endpoint works through push; unsubscribe removes the last device.
    assert member.post("/api/notify/test/push").status_code == 200
    assert member.request("DELETE", "/api/account/push", json={"endpoint": "https://push.example.org/send/def"}).json()["devices"] == 0
    assert not member.get("/api/state").json()["user"]["has_push"]


def test_push_requires_server_configuration(client):
    member = signup_member(client)
    assert member.put("/api/account/push", json={"subscription": SUB}).status_code == 409
    assert TestClient(app).get("/api/setup").json()["vapid_public_key"] == ""
    assert member.get("/api/state").json()["connections"]["push_available"] is False
