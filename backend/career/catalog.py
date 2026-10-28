"""Shared job catalog (docs/CATALOG_DESIGN.md).

Phase 1: every posting from an approved public source is also stored once
under SYSTEM, whichever member collected it and whether or not it passed their
keywords. Only public facts are kept; nothing records who collected a posting.

Phase 2, starter results: a member with no enabled source of their own
searches the catalog's recent postings instead, through the same keyword
screen, JEV and evaluation budget as any search. Measure it with:

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
# Starter results use postings seen in a source's fetch this recently, so a
# posting that left its board (usually: filled or closed) stops being offered.
STARTER_DAYS = 7

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


def record(jobs):
    """Store or refresh a source's postings in the catalog. Never raises: the
    catalog must not break a member's search."""
    if not settings.catalog_enabled:
        return
    eligible = [j for j in jobs if j.get("source") in CATALOG_SOURCES and j.get("url") and not j.get("partial")]
    if not eligible:
        return
    try:
        with _lock, Session() as db:
            stamp = now()
            for job in eligible:
                key = posting_key(job)
                existing = read(db, key, None, user_id=SYSTEM)
                if existing is None and (twin := twin_of(db, job)):
                    put(db, "posting", twin, {**read(db, twin, user_id=SYSTEM), "last_seen": stamp}, user_id=SYSTEM)
                    continue
                existing = existing or {}
                facts = {k: job[k] for k in PUBLIC_FIELDS if job.get(k) is not None}
                put(db, "posting", key, {**existing, **facts, "first_seen": existing.get("first_seen", stamp), "last_seen": stamp}, user_id=SYSTEM)
                if not existing:
                    from .service import body_hash

                    # Like members' ingest: the first posting with this text keeps the index.
                    index = "posting-body:" + body_hash(job.get("description") or "")
                    if read(db, index, None, user_id=SYSTEM) is None:
                        put(db, "posting-body", index, {"key": key}, user_id=SYSTEM)
            purge(db)
    except Exception:
        log.exception("Catalog update failed; members' searches are unaffected")


def starter_on(db):
    """Whether the scoped member's searches draw on the catalog: no enabled source of their own."""
    return settings.catalog_enabled and settings.catalog_starter and not any(s.data.get("enabled") for s in rows(db, "source"))


def has_postings(db):
    return db.query(Record.id).filter_by(user_id=SYSTEM, kind="posting").first() is not None


def starter_postings(db):
    """Recent, open catalog postings the scoped member has no job for yet, newest first."""
    from .service import expired

    since = (datetime.now(timezone.utc) - timedelta(days=STARTER_DAYS)).isoformat()
    # A member's job and its catalog posting share the fingerprint in their keys.
    known = {r.key.removeprefix("job:") for r in rows(db, "job")}
    found = [
        r.data
        for r in db.query(Record).filter_by(user_id=SYSTEM, kind="posting").all()
        if (r.data.get("last_seen") or "") >= since and not expired(r.data) and r.key.removeprefix("posting:") not in known
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
