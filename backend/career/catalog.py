"""Shared job catalog (docs/CATALOG_DESIGN.md).

Phase 1: every posting from an approved public source is also stored once
under SYSTEM, whichever member collected it and whether or not it passed their
keywords. Only public facts are kept; nothing records who collected a posting.

Phase 2, starter results: a member with no enabled source of their own
searches the catalog's open postings instead, through the same keyword
screen, JEV and evaluation budget as any search.

Phase 3 (career/collector.py): with CATALOG_SHARED on, public sources are read
once for everyone and every member's search draws on the whole catalog.
Measure it with:

    python -m career.catalog_report      (on Render: Shell tab, from /app)
"""

import logging
import threading
from datetime import datetime, timezone, timedelta
from .config import settings
from .db import Record, Session, SYSTEM, now, put, read, rows

log = logging.getLogger(__name__)

# Sources whose terms allow central storage (see the design doc). Remotive,
# careers pages, RSS, mailbox and manual postings stay private to members.
CATALOG_SOURCES = ("ReliefWeb", "Greenhouse", "Lever", "Workable", "SmartRecruiters", "Ashby")
PUBLIC_FIELDS = ("title", "company", "location", "description", "url", "deadline", "posted", "source", "external_id")
RETENTION_DAYS = 90
# Retention: a posting has left its source (usually filled or closed) once its
# source has been fetched successfully for this long without listing it.
# Measured against the source's own fetches, so a pause in searching never
# retires postings. Starter results, evaluations and alerts skip such postings.
GONE_AFTER_DAYS = 7

_lock = threading.Lock()
_last_purge = {"at": None}


def posting_key(job):
    from .service import fingerprint  # local import: service imports this module

    return "posting:" + fingerprint(job)


def twin_of(db, job):
    """The catalog posting this one cross-posts (same text, title, employer and
    location under another URL), as members' ingest detects it, or None."""
    from .service import body_hash

    index = read(db, "posting-body:" + body_hash(job.get("description") or ""), None, user_id=SYSTEM)
    if not index:
        return None
    twin = read(db, index["key"], None, user_id=SYSTEM)
    if twin and all((twin.get(k) or "").lower() == (job.get(k) or "").lower() for k in ("title", "company", "location")):
        return index["key"]
    return None


def seen_in(posting, stamp, feed):
    """The posting, listed now by `feed` (a feed key, or None when unknown)."""
    feeds = sorted({*(posting.get("feeds") or []), feed}) if feed else posting.get("feeds")
    return {**posting, "last_seen": stamp, **({"feeds": feeds} if feeds else {})}


def record(jobs, feed=None, complete=True):
    """Store or refresh one read of a source in the catalog. Never raises: the
    catalog must not break a member's search.

    `feed` is the read's feed key (collector.feed_key); `complete` is False when
    the read may have left postings out (a search capped at its newest results,
    or a read cut short by the time budget). Retention relies on both."""
    if not settings.catalog_enabled:
        return
    eligible = [j for j in jobs if j.get("source") in CATALOG_SOURCES and j.get("url") and not j.get("partial")]
    # Postings a fetch listed but did not read again because the reader already had them.
    listed = [j for j in jobs if j.get("partial") and j.get("url")]
    if not eligible and not listed and not feed:
        return
    try:
        with _lock, Session() as db:
            stamp = now()
            sources = {j["source"] for j in eligible}
            dates = []
            for job in listed:
                key = posting_key(job)
                existing = read(db, key, None, user_id=SYSTEM)
                if existing:
                    put(db, "posting", key, seen_in(existing, stamp, feed), user_id=SYSTEM)
                    sources.add(existing.get("source"))
                    dates.append(existing.get("posted"))
            for job in eligible:
                dates.append(job.get("posted"))
                key = posting_key(job)
                existing = read(db, key, None, user_id=SYSTEM)
                if existing is None and (twin := twin_of(db, job)):
                    put(db, "posting", twin, seen_in(read(db, twin, user_id=SYSTEM), stamp, feed), user_id=SYSTEM)
                    continue
                existing = existing or {}
                facts = {k: job[k] for k in PUBLIC_FIELDS if job.get(k) is not None}
                put(db, "posting", key, seen_in({**existing, **facts, "first_seen": existing.get("first_seen", stamp)}, stamp, feed), user_id=SYSTEM)
                if not existing:
                    from .service import body_hash

                    # Like members' ingest: the first posting with this text keeps the index.
                    index = "posting-body:" + body_hash(job.get("description") or "")
                    if read(db, index, None, user_id=SYSTEM) is None:
                        put(db, "posting-body", index, {"key": key}, user_id=SYSTEM)
            # Each feed's latest successful read, the clock the retention rule runs on.
            # A capped read only vouches for postings at least as new as the oldest it returned.
            if feed:
                dated = sorted(d for d in dates if d)
                put(db, "catalog-fetch", "catalog-fetch:" + feed, {"at": stamp, "complete": complete, "oldest": dated[0] if dated else None}, user_id=SYSTEM)
            # Per source too, for the report.
            for source in sources - {None}:
                put(db, "catalog-fetch", "catalog-fetch:" + source, {"at": stamp}, user_id=SYSTEM)
            purge(db)
    except Exception:
        log.exception("Catalog update failed; members' searches are unaffected")


def starter_on(db):
    """Whether the scoped member gets starter results: no enabled source of their own."""
    return settings.catalog_enabled and settings.catalog_starter and not any(s.data.get("enabled") for s in rows(db, "source"))


def pool_on(db):
    """Whether the scoped member's search draws on the whole catalog."""
    return starter_on(db) or (settings.catalog_enabled and settings.catalog_shared)


def has_postings(db):
    return db.query(Record.id).filter_by(user_id=SYSTEM, kind="posting").first() is not None


def last_fetches(db):
    """Feed key (or source name) -> its latest successful read: {at, complete, oldest}."""
    return {r.key.removeprefix("catalog-fetch:"): r.data for r in db.query(Record).filter_by(user_id=SYSTEM, kind="catalog-fetch").all()}


def _when(stamp):
    try:
        d = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def is_gone(posting, fetches):
    """Whether every feed that listed the posting has read successfully for
    GONE_AFTER_DAYS since without listing it. A capped read (ReliefWeb returns
    its newest postings) counts only for postings newer than the oldest it
    returned: older ones may simply have dropped out of its window. Postings
    collected before feeds were recorded have none and are never retired here;
    deadlines and the 90-day purge still apply."""
    seen, feeds = _when(posting.get("last_seen")), posting.get("feeds") or []
    if not (seen and feeds):
        return False
    for feed in feeds:
        clock = fetches.get(feed) or {}
        at = _when(clock.get("at"))
        if not at or at - seen < timedelta(days=GONE_AFTER_DAYS):
            return False
        if not clock.get("complete"):
            oldest, posted = _when(clock.get("oldest")), _when(posting.get("posted"))
            if not (oldest and posted and posted >= oldest):
                return False
    return True


def unlisted(db, job_keys):
    """Of these member job keys, the ones whose catalog posting has left its
    source, mapped to when it was last listed. Jobs from sources outside the
    catalog are never included."""
    if not settings.catalog_enabled:
        return {}
    fetches = last_fetches(db)
    keys = ["posting:" + k.removeprefix("job:") for k in job_keys]
    found = {}
    for i in range(0, len(keys), 500):  # SQLite caps the number of bound parameters
        for r in db.query(Record).filter(Record.user_id == SYSTEM, Record.kind == "posting", Record.key.in_(keys[i:i + 500])).all():
            if is_gone(r.data, fetches):
                found["job:" + r.key.removeprefix("posting:")] = r.data["last_seen"]
    return found


def open_postings(db):
    """Open catalog postings, still listed at their source, that the scoped
    member has no job for yet, newest first."""
    from .service import expired

    fetches = last_fetches(db)
    # A member's job and its catalog posting share the fingerprint in their keys.
    known = {r.key.removeprefix("job:") for r in rows(db, "job")}
    found = [
        r.data
        for r in db.query(Record).filter_by(user_id=SYSTEM, kind="posting").all()
        if not is_gone(r.data, fetches) and not expired(r.data) and r.key.removeprefix("posting:") not in known
    ]
    found.sort(key=lambda d: d.get("last_seen") or "", reverse=True)
    return [{k: d[k] for k in PUBLIC_FIELDS if d.get(k) is not None} for d in found]


def purge(db, force=False):
    """Delete postings unseen for RETENTION_DAYS, at most once a day."""
    current = datetime.now(timezone.utc)
    if not force and _last_purge["at"] and current - _last_purge["at"] < timedelta(days=1):
        return 0
    _last_purge["at"] = current
    cutoff = (current - timedelta(days=RETENTION_DAYS)).isoformat()
    old = [r for r in db.query(Record).filter_by(user_id=SYSTEM, kind="posting").all() if (r.data.get("last_seen") or "") < cutoff]
    gone = {r.key for r in old}
    for row in old:
        db.delete(row)
    for row in db.query(Record).filter_by(user_id=SYSTEM, kind="posting-body").all():
        if row.data.get("key") in gone:
            db.delete(row)
    db.commit()
    return len(old)
