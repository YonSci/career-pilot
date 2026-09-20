from concurrent.futures import ThreadPoolExecutor, as_completed
import contextvars
from datetime import datetime, timezone, timedelta
import hashlib
import logging
from typing import TypedDict
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse
from sqlalchemy.exc import IntegrityError
from sqlalchemy import update
from langgraph.graph import StateGraph, START, END
from .db import Record, User, Session, put, read, rows, find, get_row, now, current_user, user_scope, user_snapshot
from .schemas import Preferences
from .sources import collect, clean_url, Context
from .relevance import screen, priority
from .ai import match_job, write_package, ai_available
from .auth import plan_limits
from .notifications import notify, notify_digest, availability as notify_ready
from .config import settings

log = logging.getLogger(__name__)
CLOSED = ("skipped", "applied", "archived")


def fingerprint(job):
    if job.get("url"):
        u = urlparse(clean_url(job["url"]))
        query = urlencode(
            sorted(
                (k, v)
                for k, v in parse_qsl(u.query)
                if not k.startswith("utm_") and k not in ("source", "ref", "trk")
            )
        )
        canonical = urlunparse(
            (u.scheme.lower(), u.netloc.lower(), u.path.rstrip("/"), "", query, "")
        )
    else:
        canonical = "|".join(
            (job.get(k) or "").strip().lower() for k in ("title", "company", "location")
        )
    return hashlib.sha256(canonical.encode()).hexdigest()


def expired(job):
    date = job.get("deadline")
    if not date:
        return False
    try:
        if len(date) == 10:
            return (
                datetime.fromisoformat(date).date() < datetime.now(timezone.utc).date()
            )
        deadline = datetime.fromisoformat(date.replace("Z", "+00:00"))
        # Time without a zone is deliberately unknown, not a fabricated UTC time.
        return deadline.tzinfo is not None and deadline < datetime.now(timezone.utc)
    except ValueError:
        return False


def body_hash(description):
    return hashlib.sha256(" ".join((description or "").lower().split()).encode()).hexdigest()


def ingest(db, job):
    """Store or refresh a posting for the scoped user. Returns (row, created)."""
    job["url"] = clean_url(job.get("url", ""))
    key = "job:" + fingerprint(job)
    existing = find(db, key)
    if job.get("partial"):
        if existing:
            return put(db, "job", key, {**existing.data, "last_seen": now()}), False
        return None, False
    if existing:
        changed = existing.data.get("description") != job["description"] or existing.data.get("deadline") != job.get("deadline")
        data = {**existing.data, **job, "last_seen": now()}
        if changed:
            data["match"] = None
            data["body_hash"] = body_hash(job["description"])
        return put(db, "job", key, data), False
    # Cross-post detection: identical employer/title/location/description under a different URL.
    digest = body_hash(job["description"])
    twin = read(db, "body:" + digest)
    if twin:
        row = find(db, twin.get("job_key", ""))
        if row and all(
            (row.data.get(k) or "").lower() == (job.get(k) or "").lower()
            for k in ("title", "company", "location")
        ):
            return put(db, "job", row.key, {**row.data, "last_seen": now()}), False
    data = {
        **job,
        "status": "new",
        "match": None,
        "created": now(),
        "last_seen": now(),
        "body_hash": digest,
    }
    try:
        row = put(db, "job", key, data)
    except IntegrityError:
        db.rollback()
        return find(db, key), False
    if not twin:
        put(db, "body", "body:" + digest, {"job_key": key})
    return row, True


def evaluate(db, row):
    profile = read(db, "profile", {})
    if not any(f.get("verified") for f in profile.get("facts", [])):
        return row
    prefs = read(db, "preferences", Preferences().model_dump())
    match = match_job(profile, row.data, prefs)
    return put(
        db,
        "job",
        row.key,
        {**row.data, "match": match, "match_attempts": 0, "match_error_at": None, "evaluated": now()},
    )


class ApplicationState(TypedDict):
    profile: dict
    job: dict
    match: dict
    package: dict


def evidence_gate(state):
    if not any(f.get("verified") for f in state["profile"].get("facts", [])):
        raise ValueError("Verify CV evidence before preparing an application.")
    if expired(state["job"]):
        raise ValueError("This job's deadline has passed.")
    return {}


def draft(state):
    return {
        "package": write_package(
            state["profile"], state["job"], state.get("match") or {}
        )
    }


graph = StateGraph(ApplicationState)
graph.add_node("check_verified_evidence", evidence_gate)
graph.add_node("prepare_documents", draft)
graph.add_edge(START, "check_verified_evidence")
graph.add_edge("check_verified_evidence", "prepare_documents")
graph.add_edge("prepare_documents", END)
application_graph = graph.compile()


def as_user(db, user_id):
    """Snapshot for background entry points that receive only a user ID."""
    user = db.get(User, user_id)
    if not user:
        raise LookupError("Unknown user")
    return user_snapshot(user)


def prepare_application(job_id, user_id):
    with Session() as db:
        try:
            snapshot = as_user(db, user_id)
        except LookupError:
            return
    with user_scope(snapshot):
        _prepare_application(job_id)


def _prepare_application(job_id):
    with Session() as db:
        job = get_row(db, job_id, "job")
        app_row = find(db, "application:" + job_id)
        if not job or not app_row or app_row.data.get("status") != "queued":
            return
        # Compare-and-swap prevents two workers from generating the same application.
        claimed = db.execute(
            update(Record)
            .where(Record.id == app_row.id, Record.updated == app_row.updated)
            .values(data={**app_row.data, "status": "preparing"}, updated=now())
        )
        db.commit()
        if not claimed.rowcount:
            return
        approval = {**app_row.data, "status": "preparing"}
        try:
            result = application_graph.invoke(
                {
                    "profile": read(db, "profile", {}),
                    "job": job.data,
                    "match": job.data.get("match") or {},
                    "package": {},
                }
            )
            package = result["package"]
            review_notes = package.pop("review_notes", [])
            put(
                db,
                "application",
                app_row.key,
                {
                    **approval,
                    "status": "review",
                    "package": package,
                    "review_notes": review_notes,
                    "completed": now(),
                    "profile_snapshot": read(db, "profile", {}),
                    "job_snapshot": job.data,
                },
            )
        except Exception as e:
            log.exception("Preparation failed for %s", job_id)
            message = (
                str(e)
                if isinstance(e, ValueError)
                else "Preparation failed. Check server logs/configuration and retry."
            )
            put(
                db,
                "application",
                app_row.key,
                {**approval, "status": "failed", "error": message},
            )


def run_scan(run_id, user_id):
    with Session() as db:
        try:
            snapshot = as_user(db, user_id)
        except LookupError:
            return
    with user_scope(snapshot):
        try:
            _run_scan(run_id)
        except Exception:
            log.exception("Search failed (run %s)", run_id)
            # A new session remains usable even when the search transaction failed.
            with Session() as db:
                run = get_row(db, run_id, "run")
                if run:
                    put(db, "run", run.key, {
                        **run.data,
                        "status": "failed",
                        "completed": now(),
                        "error": "Search stopped unexpectedly. Check the server's error log, then retry.",
                    })


def needs_evaluation(data):
    match = data.get("match")
    if not match:
        return True
    return bool(ai_available() and match.get("mode") == "keyword")


def in_backoff(data):
    if (data.get("match_attempts") or 0) < 3 or not data.get("match_error_at"):
        return False
    last = datetime.fromisoformat(data["match_error_at"])
    return datetime.now(timezone.utc) - last < timedelta(hours=settings.match_retry_hours)


def alertable(data, prefs):
    match = data.get("match")
    return bool(
        match
        and match.get("mode") == "ai"
        and match["score"] >= prefs["min_score"]
        and data.get("status") not in CLOSED
        and not expired(data)
        and not any(r["mandatory"] and r["status"] == "not_met" for r in match.get("requirements", []))
    )


class OutOfTime(Exception):
    """Raised inside a worker when the search's time budget is spent before the model call."""


def evaluate_within(deadline, profile, job, prefs):
    if datetime.now(timezone.utc) >= deadline:
        raise OutOfTime()
    return match_job(profile, job, prefs)


def evaluation_budget():
    plan = (current_user() or {}).get("plan", "free")
    return min(settings.max_matches_per_run, plan_limits(plan)["evaluations_per_run"])


def _run_scan(run_id):
    with Session() as db:
        run = get_row(db, run_id, "run")
        if not run:
            return
        result = {
            "status": "running",
            "created": run.data.get("created", now()),
            "trigger": run.data.get("trigger", "manual"),
            "added": 0,
            "matched": 0,
            "sources": [],
            "alerts": 0,
            "delivered": {},
        }
        put(db, "run", run.key, result)
        prefs = {**Preferences().model_dump(), **read(db, "preferences", {})}
        sources = rows(db, "source")
        if not any(source.data.get("enabled") for source in sources):
            result.setdefault("warnings", []).append(
                "No job sources configured. Add a feed in Job sources, then run a new search."
            )
        profile = read(db, "profile", {})
        if not any(f.get("verified") for f in profile.get("facts", [])):
            result.setdefault("warnings", []).append(
                "No verified CV evidence. Review and save facts in My evidence to evaluate job matches."
            )
        if not ai_available():
            result.setdefault("warnings", []).append(
                "No OpenAI API key on this account: postings are ranked by keyword overlap only. Add a key under Account for requirement-level evaluation."
            )
        started_at = datetime.now(timezone.utc)
        deadline = started_at + timedelta(minutes=settings.scan_time_budget_minutes)
        known_urls = {r.data.get("url") for r in rows(db, "job") if r.data.get("url")}
        seen_mail = {r.data["id"] for r in rows(db, "mail")}
        ctx = Context(known_urls=known_urls, seen_mail=seen_mail, deadline=deadline)
        # Sources deferred by an earlier search go first.
        sources.sort(key=lambda s: (0 if s.data.get("deferred_at") else 1, s.data.get("deferred_at") or ""))
        for source in sources:
            if not source.data.get("enabled"):
                continue
            label = source.data["kind"] + (": " + source.data["value"] if source.data.get("value") else "")
            if datetime.now(timezone.utc) > deadline:
                put(db, "source", source.key, {**source.data, "deferred_at": now()})
                result["sources"].append({"name": label, "status": "deferred", "error": "Skipped: the search's time budget was used up; this source runs first next time."})
                continue
            if source.data.get("deferred_at"):
                put(db, "source", source.key, {k: v for k, v in source.data.items() if k != "deferred_at"})
            result["progress"] = "Reading " + label
            put(db, "run", run.key, result)
            fetched_before = ctx.pages_fetched
            try:
                jobs, mail_ids = collect(source.data, None, ctx)
                relevant = added = 0
                for job in jobs:
                    if job.get("partial"):
                        ingest(db, job)
                        continue
                    verdict = screen(job, prefs)
                    if not verdict["keep"]:
                        continue
                    job["screen"] = {k: v for k, v in verdict.items() if k != "keep"}
                    row, created = ingest(db, job)
                    if row is not None and row.data.get("url"):
                        ctx.known_urls.add(row.data["url"])
                    relevant += 1
                    added += int(created)
                for mid in mail_ids:
                    put(db, "mail", "mail:" + mid, {"id": mid})
                ctx.mail_ids.clear()
                result["added"] += added
                result["sources"].append(
                    {
                        "name": label,
                        "status": "ok",
                        "received": len(jobs),
                        "relevant": relevant,
                        "added": added,
                        "pages": ctx.pages_fetched - fetched_before,
                    }
                )
            except Exception as e:
                db.rollback()
                log.exception("Source failed: %s", label)
                message = (
                    str(e)
                    if isinstance(e, ValueError)
                    else "Feed request failed. Check credentials, identifier, and provider availability."
                )
                result["sources"].append({"name": label, "status": "failed", "error": message})
            put(db, "run", run.key, result.copy())
        if ctx.skipped_for_budget:
            result.setdefault("warnings", []).append(
                f"{ctx.skipped_for_budget} posting pages were left for the next search because of the per-run page limit."
            )
        # Evaluate the most promising unevaluated postings first, within budget.
        candidates = [
            r for r in rows(db, "job")
            if r.data.get("status") not in CLOSED
            and not expired(r.data)
            and needs_evaluation(r.data)
            and not in_backoff(r.data)
        ]
        candidates.sort(key=lambda r: priority(r.data))
        budget = evaluation_budget()
        batch = candidates[:budget]
        verified_profile = profile if any(f.get("verified") for f in profile.get("facts", [])) else None
        if batch and verified_profile:
            # Model calls run a few at a time; the database is written from this thread only.
            total = len(batch)
            result["progress"] = f"Evaluating 0 of {total}: " + batch[0].data["title"]
            put(db, "run", run.key, result)
            with ThreadPoolExecutor(max_workers=settings.evaluation_workers) as pool:
                # A Context can be entered by one thread at a time, so every task gets its own copy.
                # Postings are submitted only while the time budget allows; running calls finish.
                futures = {}
                for row in batch:
                    if datetime.now(timezone.utc) >= deadline:
                        break
                    futures[pool.submit(contextvars.copy_context().run, evaluate_within, deadline, verified_profile, row.data, prefs)] = row
                skipped_for_time = len(batch) - len(futures)
                done = 0
                for future in as_completed(futures):
                    row = futures[future]
                    done += 1
                    try:
                        match = future.result()
                        put(
                            db,
                            "job",
                            row.key,
                            {**row.data, "match": match, "match_attempts": 0, "match_error_at": None, "evaluated": now()},
                        )
                        if match:
                            result["matched"] += 1
                    except OutOfTime:
                        # Queued after the budget ran out: left unevaluated, not counted as a failure.
                        skipped_for_time += 1
                        continue
                    except Exception:
                        db.rollback()
                        log.exception("Match evaluation failed for %s", row.data.get("title"))
                        attempts = (row.data.get("match_attempts") or 0) + 1
                        put(db, "job", row.key, {**row.data, "match_attempts": attempts, "match_error_at": now()})
                        result.setdefault("warnings", []).append(
                            "A match could not be evaluated; it will be retried."
                        )
                    result["progress"] = f"Evaluating {done} of {len(futures)}: " + row.data["title"]
                    put(db, "run", run.key, result)
                if skipped_for_time:
                    result.setdefault("warnings", []).append(
                        f"{skipped_for_time} postings were left for the next search because the time budget was used up."
                    )
        if len(candidates) > budget:
            result.setdefault("warnings", []).append(
                f"{len(candidates) - budget} postings await evaluation in the next search (limit {budget} per run)."
            )
        # Announce qualifying matches: never-announced ones, plus recent matches
        # that an enabled channel has not received yet (channel linked later).
        channels = prefs.get("notify_channels", [])
        if not prefs.get("alerts_enabled") and channels:
            result.setdefault("warnings", []).append(
                "Alerts are switched off in Preferences, so no Telegram or email messages are sent. Turn on 'Send matching job alerts' to receive them."
            )
        if prefs.get("alerts_enabled"):
            announced = {}
            for r in rows(db, "alert"):
                announced.setdefault(r.data.get("job_id"), set()).add(r.data.get("channel"))
            recent_cutoff = (datetime.now(timezone.utc) - timedelta(days=settings.alert_catchup_days)).isoformat()
            ready_channels = [c for c in channels if notify_ready(db).get(c)]
            fresh = []
            for r in rows(db, "job"):
                if not alertable(r.data, prefs):
                    continue
                sent = announced.get(r.id, set())
                if "inapp" not in sent:
                    fresh.append(r)
                elif (r.data.get("evaluated") or "") >= recent_cutoff and any(c not in sent for c in ready_channels):
                    fresh.append(r)
            fresh.sort(key=lambda r: -(r.data["match"]["score"]))
            fresh = fresh[: prefs["max_alerts_per_run"]]
            outcomes = {}
            # Email is bundled into one summary per search; other channels follow alert_mode.
            digest_channels = [
                c for c in channels
                if prefs.get("alert_mode") == "digest" or (c == "email" and prefs.get("email_digest", True))
            ]
            per_job_channels = [c for c in channels if c not in digest_channels]
            for row in fresh:
                for channel, status in notify(db, row.id, row.data, row.data["match"], per_job_channels).items():
                    outcomes[channel] = status
            if fresh and digest_channels:
                outcomes.update(notify_digest(db, [(r.id, r.data, r.data["match"]) for r in fresh], digest_channels))
            result["alerts"] = len(fresh)
            result["delivered"] = outcomes
        # Retire postings that have disappeared from every feed and were never shortlisted.
        cutoff = datetime.now(timezone.utc) - timedelta(days=settings.archive_after_days)
        archived = 0
        for row in rows(db, "job"):
            data = row.data
            if data.get("status") != "new" or data.get("source") == "Manual":
                continue
            last_seen = data.get("last_seen") or data.get("created") or now()
            try:
                seen_at = datetime.fromisoformat(last_seen)
            except ValueError:
                continue
            if seen_at < cutoff:
                put(db, "job", row.key, {**data, "status": "archived", "archived": now()})
                archived += 1
        if archived:
            result["archived"] = archived
        result["status"] = "completed"
        result.pop("progress", None)
        result["completed"] = now()
        put(db, "run", run.key, result)
