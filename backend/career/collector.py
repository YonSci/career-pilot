"""Shared collector, phase 3 of docs/CATALOG_DESIGN.md.

Each distinct public source, a "feed" (a ReliefWeb search or an employer
board), is read once for everyone and its postings go to the catalog. Feeds
are the owner's curated list plus, when CATALOG_SHARED is on, every member's
enabled ReliefWeb and employer-board sources. With CATALOG_SHARED on, a
member's search skips a source whose feed was read recently and draws on the
whole catalog instead; a feed not read recently is read in the member's search
as before, which also counts as the shared read.

Feed records hold a source's kind and value and how it was last read, never
which members added it. The owner sees curated feeds by name and members'
feeds only as counts: a search term or board can reveal who added it.
"""

import hashlib
import logging
import threading
from collections import Counter
from datetime import datetime, timezone, timedelta
from .config import settings
from .db import Record, Session, SYSTEM, now, put, read
from .sources import Context, collect, validate_source, RELIEFWEB_DEFAULT_QUERY
from . import catalog

log = logging.getLogger(__name__)
CHECK_EVERY = 300
# Source kinds whose postings the catalog may hold (catalog.CATALOG_SOURCES).
FEED_KINDS = ("reliefweb", "greenhouse", "lever", "workable", "smartrecruiters", "ashby")


def feed_value(kind, value):
    value = (value or "").strip()
    return (value or RELIEFWEB_DEFAULT_QUERY) if kind == "reliefweb" else value


def feed_key(kind, value):
    return f"feed:{kind}:" + hashlib.sha256(feed_value(kind, value).encode()).hexdigest()[:20]


def member_feeds(db):
    """(kind, value) of members' enabled feed sources -> how many members have it."""
    counts = Counter()
    for r in db.query(Record).filter(Record.kind == "source", Record.user_id != SYSTEM).all():
        if r.data.get("enabled", True) and r.data.get("kind") in FEED_KINDS:
            counts[(r.data["kind"], feed_value(r.data["kind"], r.data.get("value")))] += 1
    return counts


def listing(db, with_members=True):
    """Curated feeds, plus members' feeds when `with_members`, with their read state."""
    stored = {r.key: r.data for r in db.query(Record).filter_by(user_id=SYSTEM, kind="catalog-feed").all()}
    found = {}
    if with_members:
        for (kind, value), n in member_feeds(db).items():
            key = feed_key(kind, value)
            found[key] = {**stored.get(key, {"kind": kind, "value": value}), "key": key, "members": n}
    for key, data in stored.items():
        if data.get("curated") and key not in found:
            found[key] = {**data, "key": key, "members": 0}
    return sorted(found.values(), key=lambda f: (not f.get("curated"), -f["members"], f["kind"], f["value"]))


def summary(db):
    """What the owner sees: curated feeds by name, members' feeds only as counts."""
    feeds = listing(db)
    members = [f for f in feeds if not f.get("curated")]
    return {
        "curated": [f for f in feeds if f.get("curated")],
        "member_feeds": len(members),
        "member_feeds_read": sum(1 for f in members if fresh(f)),
        "member_feeds_failing": sum(1 for f in members if f.get("error")),
    }


def _age(stamp):
    try:
        return datetime.now(timezone.utc) - datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return None


def fresh(state):
    """Read successfully within SHARED_FETCH_HOURS: members' searches can use the catalog."""
    age = _age((state or {}).get("last_ok"))
    return age is not None and age < timedelta(hours=settings.shared_fetch_hours)


def due(state):
    """Not tried within SHARED_FETCH_HOURS (a failing feed waits too, rather than hammering)."""
    age = _age((state or {}).get("last_try"))
    return age is None or age >= timedelta(hours=settings.shared_fetch_hours)


def mark(db, kind, value, ok, received=0, error=""):
    """Record one read of a feed, by the collector or a member's search."""
    key = feed_key(kind, value)
    state = read(db, key, {}, user_id=SYSTEM) or {}
    data = {**state, "kind": kind, "value": feed_value(kind, value), "last_try": now()}
    if ok:
        data.update(last_ok=data["last_try"], received=received, error="")
    else:
        data["error"] = (error or "Read failed")[:300]
    put(db, "catalog-feed", key, data, user_id=SYSTEM)


def read_feed(db, feed, ctx):
    """Read one feed into the catalog. Returns its postings; failures are recorded, then raised."""
    try:
        jobs, _ = collect({"kind": feed["kind"], "value": feed["value"]}, None, ctx)
    except Exception as e:
        mark(db, feed["kind"], feed["value"], False, error=str(e) if isinstance(e, ValueError) else type(e).__name__)
        raise
    catalog.record(jobs)
    mark(db, feed["kind"], feed["value"], True, received=len(jobs))
    return jobs


def run_cycle(stop=None):
    """Read every feed that is due. Returns how many were read."""
    if not settings.catalog_enabled:
        return 0
    with Session() as db:
        todo = [f for f in listing(db, with_members=settings.catalog_shared) if due(f)]
        if not todo:
            return 0
        # Postings already in the catalog come back as "partial" entries: their
        # pages are not read again, but they count as still listed.
        known = {r.data.get("url") for r in db.query(Record).filter_by(user_id=SYSTEM, kind="posting").all()}
        ctx = Context(known_urls=known, deadline=datetime.now(timezone.utc) + timedelta(minutes=settings.scan_time_budget_minutes))
        done = 0
        for feed in todo:
            if (stop and stop.is_set()) or ctx.out_of_time():
                break
            try:
                read_feed(db, feed, ctx)
                done += 1
            except Exception as e:
                log.warning("Shared feed %s failed: %s", feed["kind"], type(e).__name__)
        return done


def loop(stop: threading.Event):
    while not stop.is_set():
        try:
            run_cycle(stop)
        except Exception:
            log.exception("Shared collection failed")
        stop.wait(CHECK_EVERY)


def add_curated(db, kind, value):
    if kind not in FEED_KINDS:
        raise ValueError("Shared sources are ReliefWeb searches and employer boards (Greenhouse, Lever, Workable, SmartRecruiters, Ashby).")
    validate_source(kind, (value or "").strip())
    key = feed_key(kind, value)
    state = read(db, key, {}, user_id=SYSTEM) or {}
    put(db, "catalog-feed", key, {**state, "kind": kind, "value": feed_value(kind, value), "curated": True, "added": state.get("added") or now()}, user_id=SYSTEM)
    return key


def remove_curated(db, key):
    row = db.query(Record).filter_by(user_id=SYSTEM, kind="catalog-feed", key=key).first()
    if not row or not row.data.get("curated"):
        raise LookupError(key)
    # Members' sources keep the feed alive (and recreate its state) when shared collection is on.
    db.delete(row)
    db.commit()
