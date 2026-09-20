"""In-process scheduling for the simple (non-Celery) deployment.

Two daemon threads run beside the API: one walks every account and starts a
search when that account's schedule is enabled and its interval has elapsed;
the other long-polls Telegram for button presses and chat linking. Both stop
with the server. Docker/Celery deployments use Celery Beat instead.
"""

import logging
import threading
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from .config import settings
from .db import Session, Record, User, put, read, rows, now, user_scope, user_snapshot
from .schemas import Preferences
from .auth import plan_limits
from .service import run_scan
from . import telegram

log = logging.getLogger(__name__)
STALE_AFTER = timedelta(minutes=30)
CHECK_EVERY = 60


def repair_stale_runs():
    """Mark searches and preparations interrupted by a previous process exit."""
    with Session() as db:
        for run in db.query(Record).filter_by(kind="run").all():
            if run.data.get("status") not in ("queued", "running"):
                continue
            try:
                started = datetime.fromisoformat(run.data.get("created", now()))
            except ValueError:
                started = datetime.now(timezone.utc)
            if datetime.now(timezone.utc) - started > STALE_AFTER:
                put(db, "run", run.key, {
                    **run.data,
                    "status": "interrupted",
                    "completed": now(),
                    "error": "The server stopped before this search finished. It was not resumed.",
                }, user_id=run.user_id)
        for app in db.query(Record).filter_by(kind="application").all():
            if app.data.get("status") == "preparing":
                try:
                    started = datetime.fromisoformat(app.data.get("approved_at", now()))
                except ValueError:
                    started = datetime.now(timezone.utc)
                if datetime.now(timezone.utc) - started > STALE_AFTER:
                    put(db, "application", app.key, {
                        **app.data,
                        "status": "failed",
                        "error": "The server stopped during preparation. Retry when ready.",
                    }, user_id=app.user_id)


def due(db):
    """True when the scoped user's scheduled search should start now."""
    if not (read(db, "schedule", {}) or {}).get("enabled"):
        return False
    prefs = {**Preferences().model_dump(), **read(db, "preferences", {})}
    interval = timedelta(hours=prefs.get("scan_interval_hours", 6))
    latest = None
    for run in rows(db, "run"):
        status = run.data.get("status")
        created = run.data.get("created", "")
        if status in ("queued", "running"):
            try:
                if datetime.now(timezone.utc) - datetime.fromisoformat(created) < STALE_AFTER:
                    return False
            except ValueError:
                pass
            continue
        if created and (latest is None or created > latest):
            latest = created
    if latest is None:
        return True
    try:
        return datetime.now(timezone.utc) - datetime.fromisoformat(latest) >= interval
    except ValueError:
        return True


def scheduled_scan(user):
    """Run one search for `user` (a snapshot dict). Caller holds no session."""
    with user_scope(user):
        with Session() as db:
            row = put(
                db,
                "run",
                "run:" + uuid4().hex,
                {"status": "queued", "created": now(), "trigger": "scheduled"},
            )
            run_id = row.id
        run_scan(run_id, user["id"])


def due_users():
    """Snapshots of accounts whose scheduled search should start now."""
    with Session() as db:
        result = []
        for user in db.query(User).all():
            if not plan_limits(user.plan)["schedule"]:
                continue
            snapshot = user_snapshot(user)
            with user_scope(snapshot):
                if due(db):
                    result.append(snapshot)
        return result


def scan_loop(stop: threading.Event):
    """Each due account runs in its own thread (a few at a time), so one slow
    mailbox or feed cannot hold up everyone else's search."""
    from concurrent.futures import ThreadPoolExecutor

    while not stop.is_set():
        try:
            users = due_users()
            if users:
                with ThreadPoolExecutor(max_workers=settings.scan_workers, thread_name_prefix="career-user-scan") as pool:
                    for user in users:
                        if stop.is_set():
                            break
                        log.info("Scheduled search starting for %s", user["email"])
                        pool.submit(_guarded_scan, user)
        except Exception:
            log.exception("Scheduler cycle failed")
        stop.wait(CHECK_EVERY)


def _guarded_scan(user):
    try:
        scheduled_scan(user)
    except Exception:
        log.exception("Scheduled search failed for %s", user.get("email"))


class Scheduler:
    def __init__(self):
        self.stop = threading.Event()
        self.threads = []

    def start(self):
        if settings.task_queue == "celery" or not settings.scheduler_enabled:
            return
        repair_stale_runs()
        self.threads.append(threading.Thread(target=scan_loop, args=(self.stop,), name="career-scan", daemon=True))
        if settings.telegram_bot_token:
            self.threads.append(threading.Thread(target=telegram.poll_forever, args=(self.stop,), name="career-telegram", daemon=True))
        for t in self.threads:
            t.start()

    def shutdown(self):
        self.stop.set()

    def status(self):
        return {
            "mode": "celery" if settings.task_queue == "celery" else ("in-process" if settings.scheduler_enabled else "off"),
            "threads": {t.name: t.is_alive() for t in self.threads},
        }


scheduler = Scheduler()
