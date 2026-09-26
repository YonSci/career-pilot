"""Public Telegram channel: the bot posts new field-relevant roles daily and a
closing-soon digest weekly, each linking back to the public listings. Runs only
when TELEGRAM_CHANNEL_ID is set and the bot is an administrator of the channel."""

import html
import logging
import threading
from datetime import datetime, timezone
from .config import settings
from .db import SYSTEM, Session, put, read, now
from . import public_jobs

log = logging.getLogger(__name__)
STATE_KEY = "channel:state"
CHECK_EVERY = 900
MAX_DAILY = 8
MAX_WEEKLY = 10


def enabled():
    return bool(settings.telegram_bot_token and settings.telegram_channel_id)


def state(db):
    return read(db, STATE_KEY, user_id=SYSTEM) or {"posted": [], "last_daily": None, "last_weekly": None, "posts": 0}


def _save(db, s):
    s["posted"] = s.get("posted", [])[-500:]
    put(db, "channel", STATE_KEY, s, user_id=SYSTEM)


def _site(tag):
    """Landing link with campaign tags, escaped for Telegram's HTML parser (a bare & is rejected)."""
    url = settings.public_url.rstrip("/") + f"/?utm_source=telegram&utm_medium=channel&utm_campaign={tag}#jobs"
    return f'<a href="{html.escape(url, quote=True)}">{html.escape(url)}</a>'


def _line(j):
    where = " · ".join(x for x in (j.get("company"), j.get("location") if j.get("location") != "Not specified" else "") if x)
    deadline = f" (closes {j['deadline'][:10]})" if j.get("deadline") else ""
    return f"• <a href=\"{html.escape(j['url'], quote=True)}\">{html.escape(j['title'])}</a>{(' — ' + html.escape(where)) if where else ''}{deadline}"


def daily_message(db):
    """New roles not yet announced. Returns (text, urls) or (None, [])."""
    s = state(db)
    seen = set(s.get("posted", []))
    fresh = [j for j in public_jobs.listings(db)["latest"] if j["url"] not in seen][:MAX_DAILY]
    if not fresh:
        return None, []
    lines = [f"<b>New roles today · {html.escape(settings.app_name)}</b>", ""] + [_line(j) for j in fresh]
    lines += ["", f"See all open roles and get matched to them: {_site('daily')}"]
    return "\n".join(lines), [j["url"] for j in fresh]


def weekly_message(db):
    closing = public_jobs.listings(db)["closing_soon"][:MAX_WEEKLY]
    if not closing:
        return None
    lines = [f"<b>Closing this week · {html.escape(settings.app_name)}</b>", ""] + [_line(j) for j in closing]
    lines += ["", f"Every posting scored against your verified CV, with the reasons: {_site('weekly')}"]
    return "\n".join(lines)


def post(kind="daily", db=None):
    """Send one post now. Returns what happened; raises on Telegram errors."""
    from .telegram import api

    if not enabled():
        raise ValueError("Set TELEGRAM_CHANNEL_ID (and make the bot an admin of the channel) first.")
    own = db is None
    db = db or Session()
    try:
        s = state(db)
        if kind == "weekly":
            text = weekly_message(db)
            urls = []
        else:
            text, urls = daily_message(db)
        if not text:
            return {"posted": False, "reason": "nothing new to post"}
        api("sendMessage", chat_id=settings.telegram_channel_id, text=text, parse_mode="HTML", disable_web_page_preview=True)
        s["posted"] = s.get("posted", []) + urls
        s["last_" + kind] = now()
        s["posts"] = s.get("posts", 0) + 1
        _save(db, s)
        log.info("Channel post sent (%s, %d roles)", kind, len(urls) or MAX_WEEKLY)
        return {"posted": True, "kind": kind, "roles": len(urls)}
    finally:
        if own:
            db.close()


def due(db):
    """Which post is due now: daily at the configured UTC hour, weekly on Monday."""
    s = state(db)
    t = datetime.now(timezone.utc)
    if t.hour < settings.telegram_channel_daily_hour:
        return None
    today = t.date().isoformat()
    if t.weekday() == 0 and (s.get("last_weekly") or "")[:10] != today:
        return "weekly"
    if (s.get("last_daily") or "")[:10] != today:
        return "daily"
    return None


def loop(stop: threading.Event):
    while not stop.is_set():
        try:
            if enabled():
                with Session() as db:
                    kind = due(db)
                    if kind:
                        post(kind, db)
        except Exception:
            log.exception("Channel post failed")
        stop.wait(CHECK_EVERY)
