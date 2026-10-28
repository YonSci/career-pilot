"""Rescore, with the current rubric and model, postings the LLM has already
evaluated or a member has decided on, so jev_report has comparison data again
straight after a rubric or model change. Searches only rescore postings still
waiting for evaluation. Uses JEV tokens, counted against JEV_MONTHLY_TOKENS.

    python -m career.jev_backfill        (at most 200 postings)
    python -m career.jev_backfill 500
"""

import contextvars
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from .config import settings
from .db import Session, User, put, read, rows, user_scope
from .schemas import Preferences, APPLICATION_STAGES
from .jev import JevCapReached, jev_enabled, jev_key, jev_state, score_job


def compared(job):
    return (job.get("match") or {}).get("mode") == "ai" or job.get("status") in ("saved", "skipped", *APPLICATION_STAGES)


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    limit = int(args[0]) if args else 200
    done = {"scored": 0, "failed": 0, "tokens": 0}
    capped = False
    with Session() as db:
        for user in db.query(User).all():
            left = limit - done["scored"] - done["failed"]
            if left <= 0 or capped:
                break
            with user_scope(user):
                profile = read(db, "profile", {})
                if not jev_enabled() or not any(f.get("verified") for f in profile.get("facts", [])):
                    continue
                prefs = {**Preferences().model_dump(), **read(db, "preferences", {})}
                stale = [
                    r for r in rows(db, "job")
                    if r.data.get("jev") and compared(r.data)
                    and r.data["jev"].get("key") != jev_key(jev_state(profile, r.data, prefs))
                ][:left]
                with ThreadPoolExecutor(max_workers=settings.jev_workers) as pool:
                    futures = {pool.submit(contextvars.copy_context().run, score_job, profile, r.data, prefs): r for r in stale}
                    for future in as_completed(futures):
                        row = futures[future]
                        try:
                            scored = future.result()
                        except JevCapReached:
                            capped = True
                            for pending in futures:
                                pending.cancel()
                            break
                        except Exception as e:
                            done["failed"] += 1
                            print(f"failed: {row.data.get('title')}: {type(e).__name__}")
                            continue
                        # Keep the sample mark: it records why the LLM evaluated this posting.
                        if row.data["jev"].get("sample"):
                            scored["sample"] = True
                        put(db, "job", row.key, {**row.data, "jev": scored})
                        done["scored"] += 1
                        done["tokens"] += scored["tokens"]
    print(f"Rescored {done['scored']} postings ({done['tokens']} input tokens); {done['failed']} failed.")
    if capped:
        print("Stopped: this month's JEV token cap (JEV_MONTHLY_TOKENS) is reached.")


if __name__ == "__main__":
    main()
