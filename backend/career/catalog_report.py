"""How the shared catalog is filling up, and how much it would save. Read-only.

    python -m career.catalog_report      (on Render: Shell tab, from /app)
"""

from collections import Counter
from datetime import datetime, timezone, timedelta
from .db import Record, Session, SYSTEM


def main():
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    with Session() as db:
        postings = db.query(Record).filter(Record.user_id == SYSTEM, Record.kind == "posting").all()
        # A member's job and its catalog posting share the fingerprint in their keys.
        jobs = db.query(Record).filter(Record.kind == "job", Record.user_id != SYSTEM).all()
        members = Counter(r.key.removeprefix("job:") for r in jobs)
        starter = [r for r in jobs if r.data.get("via") == "catalog"]
    if not postings:
        print("The catalog is empty. It fills as members' searches read ReliefWeb and employer job boards.")
        return
    held = [members[r.key.removeprefix("posting:")] for r in postings]
    fresh = sum(1 for r in postings if (r.data.get("last_seen") or "") >= week_ago)
    size = sum(len(r.data.get("description") or "") for r in postings)
    print(f"Catalog postings: {len(postings)} ({fresh} seen in the last 7 days), descriptions {size / 1e6:.1f} MB")
    print("By source: " + ", ".join(f"{s} {n}" for s, n in Counter(r.data.get("source") for r in postings).most_common()))
    print(f"Kept by no member (rejected by everyone's keywords): {held.count(0)}")
    print(f"Kept by one member: {held.count(1)}; by two or more: {sum(1 for h in held if h >= 2)} (most: {max(held)})")
    print(f"Member copies of catalog postings: {sum(held)}; stored once in the catalog: {sum(1 for h in held if h)}")
    evaluated = sum(1 for r in starter if (r.data.get("match") or {}).get("mode") == "ai")
    print(f"Starter results: {len(starter)} jobs for {len({r.user_id for r in starter})} members without sources, {evaluated} evaluated")


if __name__ == "__main__":
    main()
