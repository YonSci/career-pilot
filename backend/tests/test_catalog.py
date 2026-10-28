"""Shared catalog, phase 1: approved public postings stored once, before keyword screening."""

from datetime import datetime, timezone, timedelta
from career import catalog, catalog_report
from career.config import settings
from career.db import Record, Session, SYSTEM, User, put
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


# --- phase 2: starter results -------------------------------------------------


def put_posting(job, days_ago=0):
    seen = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    with Session() as db:
        put(db, "posting", catalog.posting_key(job), {**job, "first_seen": seen, "last_seen": seen}, user_id=SYSTEM)


def member_jobs(email):
    with Session() as db:
        user = db.query(User).filter_by(email=email).one()
        return {r.data["url"]: r.data for r in db.query(Record).filter_by(user_id=user.id, kind="job").all()}


def test_members_without_sources_get_starter_results_from_the_catalog(client, monkeypatch, capsys):
    fresh = {**JOB, "source": "ReliefWeb", "url": "https://example.org/jobs/fresh"}
    put_posting(fresh)
    put_posting({**JOB, "source": "Greenhouse", "url": "https://example.org/jobs/cleaner", "title": "Office cleaner", "description": "Cleaning offices daily."})
    put_posting({**JOB, "source": "Greenhouse", "url": "https://example.org/jobs/stale"}, days_ago=catalog.STARTER_DAYS + 1)
    put_posting({**JOB, "source": "Greenhouse", "url": "https://example.org/jobs/closed", "deadline": "2020-01-01"})

    member = signup_member(client)
    assert member.get("/api/state").json()["catalog_starter"] is True
    assert member.post("/api/scan").status_code in (200, 202)
    # Recent, open, keyword-matching postings only; marked as coming from the catalog.
    jobs = member_jobs("member@example.org")
    assert set(jobs) == {fresh["url"]} and jobs[fresh["url"]]["via"] == "catalog" and jobs[fresh["url"]]["screen"]["keyword_hits"]
    run = member.get("/api/state").json()["runs"][0]
    assert run["added"] == 1 and run["sources"][0]["name"].startswith("Recent postings")
    assert not any("No job sources" in w for w in run.get("warnings", []))

    # A skipped job stays skipped; a second search offers nothing it already has.
    job_id = next(j["id"] for j in member.get("/api/state").json()["jobs"])
    assert member.put(f"/api/jobs/{job_id}/decision", json={"status": "skipped"}).status_code == 200
    member.post("/api/scan")
    run = member.get("/api/state").json()["runs"][0]
    # Only the keyword-rejected posting is screened again; nothing is added.
    assert run["sources"][0]["received"] == 1 and run["added"] == 0 and not any("No job sources" in w for w in run.get("warnings", []))
    assert member_jobs("member@example.org")[fresh["url"]]["status"] == "skipped"

    # Members with a source of their own are unchanged: no catalog postings.
    monkeypatch.setattr("career.service.collect", lambda *a, **k: ([], []))
    client.post("/api/sources", json={"kind": "greenhouse", "value": "example"})
    client.post("/api/scan")
    assert fresh["url"] not in {j["url"] for j in client.get("/api/state").json()["jobs"]}

    catalog_report.main()
    assert "Starter results: 1 jobs for 1 members without sources" in capsys.readouterr().out


def test_starter_results_off_or_empty_catalog_keep_the_old_warning(client, monkeypatch):
    member = signup_member(client)
    member.post("/api/scan")
    assert any("no recent shared postings yet" in w for w in member.get("/api/state").json()["runs"][0]["warnings"])
    monkeypatch.setattr(settings, "catalog_starter", False)
    put_posting({**JOB, "source": "ReliefWeb", "url": "https://example.org/jobs/fresh"})
    member.post("/api/scan")
    assert member_jobs("member@example.org") == {}
    assert any(w.startswith("No job sources configured. Add") for w in member.get("/api/state").json()["runs"][0]["warnings"])


def test_scheduled_starter_searches_need_a_verified_cv(client, monkeypatch):
    from tests.test_schedule import is_due
    from tests.test_workflow import verified_profile

    member = signup_member(client)
    assert is_due("member@example.org") is False
    verified_profile(member)
    assert is_due("member@example.org") is True
    monkeypatch.setattr(settings, "catalog_starter", False)
    assert is_due("member@example.org") is False
