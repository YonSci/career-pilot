"""Scheduled searches: on by default for new members, idle without sources; one-off reminder."""

from career import schedule_reminder
from career.config import settings
from career.db import Session, User, user_scope, user_snapshot
from career.scheduler import due
from tests.conftest import signup_member


def is_due(email):
    with Session() as db:
        user = db.query(User).filter_by(email=email).one()
        with user_scope(user_snapshot(user)):
            return due(db)


def test_new_members_get_scheduled_searches_that_wait_for_a_source(client):
    member = signup_member(client)
    assert member.get("/api/state").json()["schedule"]["enabled"] is True
    assert is_due("member@example.org") is False  # no source yet
    assert member.post("/api/sources", json={"kind": "greenhouse", "value": "example"}).status_code == 200
    assert is_due("member@example.org") is True


def test_reminder_lists_then_sends_once_to_members_with_sources_and_no_schedule(client, monkeypatch, capsys):
    off = signup_member(client, email="off@example.org")
    off.post("/api/sources", json={"kind": "greenhouse", "value": "example"})
    off.put("/api/schedule", json={"enabled": False})
    on = signup_member(client, email="on@example.org")
    on.post("/api/sources", json={"kind": "greenhouse", "value": "example"})
    idle = signup_member(client, email="idle@example.org")
    idle.put("/api/schedule", json={"enabled": False})  # no sources: nothing to schedule

    monkeypatch.setattr(settings, "smtp_host", "smtp.example.org")
    monkeypatch.setattr(settings, "email_from", "jobs@example.org")
    sent = []
    monkeypatch.setattr(schedule_reminder, "email_send", lambda subject, text, to=None: sent.append((to, subject, text)))

    schedule_reminder.main([])
    out = capsys.readouterr().out
    assert "off@example.org: email" in out and "on@example.org" not in out and "idle@example.org" not in out
    assert "Dry run" in out and sent == []

    schedule_reminder.main(["--send"])
    assert [s[0] for s in sent] == ["off@example.org"]
    assert "Search automatically" in sent[0][2] and "Reminded 1 of 1 members." in capsys.readouterr().out

    schedule_reminder.main(["--send"])
    assert len(sent) == 1 and "No members to remind." in capsys.readouterr().out
