"""How the shared catalog is filling up, and how much it would save. Read-only.

    python -m career.catalog_report      (on Render: Shell tab, from /app)
"""

from collections import Counter
from datetime import datetime, timezone, timedelta
from .db import Record, Session, SYSTEM
from .catalog import is_gone, last_fetches
from .collector import summary as feed_summary
from .config import settings


def main():
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    with Session() as db:
        postings = db.query(Record).filter(Record.user_id == SYSTEM, Record.kind == "posting").all()
        # A member's job and its catalog posting share the fingerprint in their keys.
        jobs = db.query(Record).filter(Record.kind == "job", Record.user_id != SYSTEM).all()
        members = Counter(r.key.removeprefix("job:") for r in jobs)
        starter = [r for r in jobs if r.data.get("via") == "catalog"]
        fetches = last_fetches(db)
        feeds = feed_summary(db)
    curated = feeds["curated"]
    print(f"Shared sources: {len(curated)} curated by the owner, {feeds['member_feeds']} distinct members' sources; "
          f"shared collection {'on' if settings.catalog_shared else 'off (members read their own; curated ones are read for everyone)'}")
    if settings.catalog_shared:
        print(f"  members' sources read in the last {settings.shared_fetch_hours:g} hours: {feeds['member_feeds_read']}, failing: {feeds['member_feeds_failing']}")
    for f in curated:
        if f.get("error"):
            print(f"  failing: {f['kind']} {f['value'][:60]}: {f['error']}")
    if not postings:
        print("The catalog is empty. It fills as members' searches read ReliefWeb and employer job boards.")
        return
    held = [members[r.key.removeprefix("posting:")] for r in postings]
    fresh = sum(1 for r in postings if (r.data.get("last_seen") or "") >= week_ago)
    size = sum(len(r.data.get("description") or "") for r in postings)
    print(f"Catalog postings: {len(postings)} ({fresh} seen in the last 7 days), descriptions {size / 1e6:.1f} MB")
    gone = sum(1 for r in postings if is_gone(r.data, fetches))
    by_source = {s: c.get("at") or "" for s, c in fetches.items() if not s.startswith("feed:")}
    print(f"No longer listed at their source (retention rule): {gone}; last successful fetch: " + (", ".join(f"{s} {a[:16]}" for s, a in sorted(by_source.items())) or "none recorded yet"))
    untied = sum(1 for r in postings if not r.data.get("feeds"))
    if untied:
        print(f"  not yet tied to a feed (collected before per-feed tracking, never retired by the rule): {untied}")
    print("By source: " + ", ".join(f"{s} {n}" for s, n in Counter(r.data.get("source") for r in postings).most_common()))
    print(f"Kept by no member (rejected by everyone's keywords): {held.count(0)}")
    print(f"Kept by one member: {held.count(1)}; by two or more: {sum(1 for h in held if h >= 2)} (most: {max(held)})")
    print(f"Member copies of catalog postings: {sum(held)}; stored once in the catalog: {sum(1 for h in held if h)}")
    evaluated = sum(1 for r in starter if (r.data.get("match") or {}).get("mode") == "ai")
    print(f"Starter results: {len(starter)} jobs for {len({r.user_id for r in starter})} members without sources, {evaluated} evaluated")


if __name__ == "__main__":
    main()
