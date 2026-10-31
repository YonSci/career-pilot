"""Shared catalog, phase 3: public sources read once for everyone; curated shared sources."""

from datetime import datetime, timezone, timedelta
from career import catalog, catalog_report, collector
from career.sources import check_board
from career.config import settings
from career.db import Record, Session, SYSTEM, put, read
from tests.conftest import signup_member
from tests.test_workflow import JOB

ACME = [
    {**JOB, "source": "Greenhouse", "url": "https://example.org/jobs/acme-1", "title": "Climate Data Scientist"},
    {**JOB, "source": "Greenhouse", "url": "https://example.org/jobs/acme-2", "title": "Hydrology Analyst"},
]


def fake_collect(calls, jobs=ACME):
    def collect(source, seen_mail=None, ctx=None):
        calls.append((source["kind"], source.get("value")))
        return list(jobs), []

    return collect


def urls(client):
    return {j["url"] for j in client.get("/api/state").json()["jobs"]}


def test_a_listed_posting_the_reader_already_has_still_counts_as_listed(client):
    # Members' fetches return known postings as partial entries; they must refresh the catalog
    # too, or the retention rule would retire every posting some member already holds.
    old = (datetime.now(timezone.utc) - timedelta(days=catalog.GONE_AFTER_DAYS + 1)).isoformat()
    with Session() as db:
        put(db, "posting", catalog.posting_key(ACME[0]), {**ACME[0], "first_seen": old, "last_seen": old}, user_id=SYSTEM)
    catalog.record([{"url": ACME[0]["url"], "partial": True}])
    with Session() as db:
        posting = read(db, catalog.posting_key(ACME[0]), user_id=SYSTEM)
        assert posting["last_seen"] > old and not catalog.is_gone(posting, catalog.last_fetches(db))
        assert "Greenhouse" in catalog.last_fetches(db)


def test_curated_shared_sources_are_read_for_everyone_once_per_interval(client, monkeypatch):
    calls = []
    monkeypatch.setattr(collector, "collect", fake_collect(calls))
    member = signup_member(client)
    assert member.post("/api/admin/catalog-feeds", json={"kind": "greenhouse", "value": "acme"}).status_code == 403
    assert client.post("/api/admin/catalog-feeds", json={"kind": "rss", "value": "https://example.org/feed"}).status_code == 422
    feeds = client.post("/api/admin/catalog-feeds", json={"kind": "greenhouse", "value": "acme"}).json()
    assert feeds["shared"] is False and [(f["kind"], f["value"]) for f in feeds["curated"]] == [("greenhouse", "acme")]

    assert collector.run_cycle() == 1 and calls == [("greenhouse", "acme")]
    assert collector.run_cycle() == 0  # read within SHARED_FETCH_HOURS
    feed = client.get("/api/admin/overview").json()["catalog_feeds"]["curated"][0]
    assert feed["received"] == 2 and feed["last_ok"] and not feed.get("error")
    # Members without sources get its postings as starter results.
    member.post("/api/scan")
    assert urls(member) == {j["url"] for j in ACME}

    # Members' own sources are not collected while shared collection is off.
    member.post("/api/sources", json={"kind": "greenhouse", "value": "other"})
    monkeypatch.setattr(settings, "shared_fetch_hours", 0)
    collector.run_cycle()
    assert ("greenhouse", "other") not in calls

    key = feeds["curated"][0]["key"]
    # The member's own source is counted for the owner, never named.
    left = client.delete(f"/api/admin/catalog-feeds/{key}").json()
    assert left["curated"] == [] and left["member_feeds"] == 1 and "other" not in str(left)
    assert client.delete(f"/api/admin/catalog-feeds/{key}").status_code == 404


def test_shared_collection_reads_each_source_once_and_members_use_the_catalog(client, monkeypatch, capsys):
    monkeypatch.setattr(settings, "catalog_shared", True)
    direct, shared = [], []
    monkeypatch.setattr("career.service.collect", fake_collect(direct))
    monkeypatch.setattr(collector, "collect", fake_collect(shared, [{**JOB, "source": "ReliefWeb", "url": "https://example.org/jobs/rw-9", "title": "GIS Lead"}]))
    member = signup_member(client)
    for c in (client, member):
        assert c.post("/api/sources", json={"kind": "greenhouse", "value": "acme"}).status_code == 200

    # First search: the feed has not been read, so the member's search reads it (and that counts for everyone).
    member.post("/api/scan")
    assert direct == [("greenhouse", "acme")] and urls(member) == {j["url"] for j in ACME}
    # Second account, same source, within the interval: no fetch, postings from the catalog.
    client.post("/api/scan")
    assert len(direct) == 1 and {j["url"] for j in ACME} <= urls(client)
    run = client.get("/api/state").json()["runs"][0]
    assert run["sources"][0]["name"].startswith("greenhouse: acme (shared, read") and run["added"] == 2

    # The collector reads members' sources too, plus the owner's curated ones; members get both.
    client.post("/api/admin/catalog-feeds", json={"kind": "reliefweb", "value": "GIS"})
    monkeypatch.setattr(settings, "shared_fetch_hours", 0)
    assert collector.run_cycle() == 2 and sorted(shared) == [("greenhouse", "acme"), ("reliefweb", "GIS")]
    monkeypatch.setattr(settings, "shared_fetch_hours", 3)
    member.post("/api/scan")
    assert "https://example.org/jobs/rw-9" in urls(member) and len(direct) == 1

    catalog_report.main()
    out = capsys.readouterr().out
    assert "Shared sources: 1 curated by the owner, 1 distinct members' sources; shared collection on" in out
    assert "members' sources read in the last 3 hours: 1, failing: 0" in out and "acme" not in out


def test_a_failing_shared_source_is_recorded_and_waits_for_the_interval(client, monkeypatch, capsys):
    def broken(source, seen_mail=None, ctx=None):
        raise ValueError("Board not found.")

    monkeypatch.setattr(collector, "collect", broken)
    client.post("/api/admin/catalog-feeds", json={"kind": "lever", "value": "gone"})
    assert collector.run_cycle() == 0
    feed = client.get("/api/admin/overview").json()["catalog_feeds"]["curated"][0]
    assert feed["error"] == "Board not found." and feed["last_try"] and not feed.get("last_ok")
    calls = []
    monkeypatch.setattr(collector, "collect", fake_collect(calls))
    collector.run_cycle()
    assert calls == []  # tried within the interval: no retry yet
    catalog_report.main()
    assert "failing: lever gone: Board not found." in capsys.readouterr().out
    with Session() as db:
        assert db.query(Record).filter_by(user_id=SYSTEM, kind="posting").count() == 0


def test_a_board_that_does_not_exist_is_refused_with_a_clear_message(client, monkeypatch):
    import httpx
    from career import sources

    def platform(request):
        return httpx.Response(200 if request.url.host == "apply.workable.com" else 404, json={"results": []})

    assert check_board("workable", "cgiar", client=httpx.Client(transport=httpx.MockTransport(platform))) is None
    try:
        check_board("greenhouse", "cgiar", client=httpx.Client(transport=httpx.MockTransport(platform)))
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "no Greenhouse employer board named cgiar" in str(e) and "boards.greenhouse.io/acme" in str(e)

    def missing(kind, value, client=None):
        raise ValueError(sources.board_missing(kind, value))

    monkeypatch.setattr(sources, "check_board", missing)
    r = client.post("/api/admin/catalog-feeds", json={"kind": "greenhouse", "value": "cgiar"})
    assert r.status_code == 422 and "no Greenhouse employer board named cgiar" in r.json()["detail"]
    assert client.post("/api/sources", json={"kind": "lever", "value": "nobody"}).status_code == 422

    # A board that disappears later shows the same message, not the exception's name.
    gone = httpx.HTTPStatusError("404", request=httpx.Request("GET", "https://x"), response=httpx.Response(404))
    assert "no Lever employer board named gone" in sources.failure_message(gone, "lever", "gone")
