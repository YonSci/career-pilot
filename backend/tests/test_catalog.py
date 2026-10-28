"""Shared catalog, phase 1: approved public postings stored once, before keyword screening."""

from datetime import datetime, timezone, timedelta
from career import catalog, catalog_report
from career.db import Record, Session, SYSTEM, put
from tests.conftest import signup_member
from tests.test_workflow import JOB

FEED = [
    {**JOB, "source": "Greenhouse", "url": "https://example.org/jobs/gh-1"},
    {**JOB, "source": "Greenhouse", "url": "https://example.org/jobs/gh-2", "title": "Office cleaner", "description": "Cleaning and tidying offices daily."},
    {**JOB, "source": "ReliefWeb", "url": "https://example.org/jobs/rw-1", "title": "Hydrology Analyst"},
    # The first posting cross-posted under another URL: kept once, as members' ingest does.
    {**JOB, "source": "ReliefWeb", "url": "https://example.org/jobs/rw-crosspost"},
    {**JOB, "source": "Remotive", "url": "https://example.org/jobs/remotive-1"},
    {**JOB, "source": "Email alert", "url": "https://example.org/jobs/mail-1"},
]


def catalog_rows():
    with Session() as db:
        return {r.data["url"]: r.data for r in db.query(Record).filter_by(user_id=SYSTEM, kind="posting").all()}


def search(client, monkeypatch):
    monkeypatch.setattr("career.service.collect", lambda *a, **k: (FEED, []))
    assert client.post("/api/sources", json={"kind": "greenhouse", "value": "example"}).status_code == 200
    assert client.post("/api/scan").status_code in (200, 202)


def test_catalog_stores_approved_postings_once_including_keyword_rejected(client, monkeypatch, capsys):
    search(client, monkeypatch)
    stored = catalog_rows()
    assert set(stored) == {"https://example.org/jobs/gh-1", "https://example.org/jobs/gh-2", "https://example.org/jobs/rw-1"}
    assert set(stored["https://example.org/jobs/gh-1"]) <= set(catalog.PUBLIC_FIELDS) | {"first_seen", "last_seen"}
    owner_jobs = {j["url"] for j in client.get("/api/state").json()["jobs"]}
    assert "https://example.org/jobs/gh-2" not in owner_jobs  # rejected by keywords, yet in the catalog

    member = signup_member(client)
    search(member, monkeypatch)
    again = catalog_rows()
    assert set(again) == set(stored)  # a second member adds no copies
    first = stored["https://example.org/jobs/gh-1"]
    assert again["https://example.org/jobs/gh-1"]["first_seen"] == first["first_seen"]

    catalog_report.main()
    out = capsys.readouterr().out
    assert "Catalog postings: 3 (3 seen in the last 7 days)" in out
    assert "Kept by no member (rejected by everyone's keywords): 1" in out
    assert "Kept by one member: 0; by two or more: 2 (most: 2)" in out


def test_a_catalog_failure_never_breaks_a_search(client, monkeypatch):
    def broken():
        raise RuntimeError("database locked")

    monkeypatch.setattr(catalog, "Session", broken)
    search(client, monkeypatch)
    run = client.get("/api/state").json()["runs"][0]
    assert run["status"] == "completed" and run["added"] >= 1
    assert catalog_rows() == {}


def test_catalog_can_be_switched_off(client, monkeypatch):
    from career.config import settings

    monkeypatch.setattr(settings, "catalog_enabled", False)
    search(client, monkeypatch)
    assert catalog_rows() == {}


def test_postings_unseen_for_90_days_are_purged(client):
    old = (datetime.now(timezone.utc) - timedelta(days=catalog.RETENTION_DAYS + 1)).isoformat()
    recent = datetime.now(timezone.utc).isoformat()
    with Session() as db:
        put(db, "posting", "posting:old", {"url": "https://example.org/old", "last_seen": old}, user_id=SYSTEM)
        put(db, "posting", "posting:new", {"url": "https://example.org/new", "last_seen": recent}, user_id=SYSTEM)
        assert catalog.purge(db, force=True) == 1
    assert set(catalog_rows()) == {"https://example.org/new"}
