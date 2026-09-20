"""Telegram long polling shared by all accounts on one bot.

Linking: the dashboard issues a short code for the signed-in user. They send
that code to the bot from their own Telegram account. A private chat that
presents a valid, unexpired code becomes that user's linked chat. Buttons only
act on jobs owned by the user whose chat pressed them. Unknown senders are
never answered.
"""

import logging
import secrets
import threading
from datetime import datetime, timezone, timedelta
import httpx
from .config import settings
from .db import Session, Record, User, SYSTEM, put, read, now, current_user, user_scope, user_snapshot

log = logging.getLogger(__name__)
LINK_TTL = timedelta(minutes=15)


def api(method, http_timeout=35, **payload):
    r = httpx.post(
        f"https://api.telegram.org/bot{settings.telegram_bot_token}/{method}",
        json=payload,
        timeout=http_timeout,
    )
    data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if r.status_code == 409:
        raise ConflictError(data.get("description", "conflict"))
    r.raise_for_status()
    if not data.get("ok"):
        raise ValueError(data.get("description", "Telegram request failed"))
    return data.get("result")


class ConflictError(Exception):
    pass


def create_link_code(db):
    code = secrets.token_hex(3).upper()
    put(db, "telegram_link", "telegram_link", {"code": code, "created": now()})
    return code


def link_status(db):
    linked = read(db, "telegram", {}) or {}
    owner_env = (current_user() or {}).get("role") == "admin" and bool(settings.telegram_chat_id)
    return {
        "bot_configured": bool(settings.telegram_bot_token),
        "linked": bool(owner_env or linked.get("chat_id")),
        "username": linked.get("username") or "",
        "linked_at": linked.get("linked_at"),
        "via_env": owner_env,
    }


def bot_username():
    try:
        return api("getMe", http_timeout=15).get("username", "")
    except Exception:
        return ""


def linked_chat(db):
    """The scoped user's chat ID."""
    if (current_user() or {}).get("role") == "admin" and settings.telegram_chat_id:
        return settings.telegram_chat_id
    return str((read(db, "telegram", {}) or {}).get("chat_id") or "")


def user_for_chat(db, chat_id):
    """Which account owns this chat, if any."""
    for row in db.query(Record).filter_by(kind="telegram").all():
        if str(row.data.get("chat_id")) == str(chat_id):
            return db.get(User, row.user_id)
    if settings.telegram_chat_id and str(chat_id) == settings.telegram_chat_id:
        return db.query(User).filter_by(role="admin").order_by(User.created).first()
    return None


def handle_message(db, message):
    chat = message.get("chat") or {}
    if chat.get("type") != "private":
        return
    text = (message.get("text") or "").strip()
    chat_id = str(chat.get("id"))
    supplied = text.removeprefix("/start").strip().upper()
    if supplied:
        for pending in db.query(Record).filter_by(kind="telegram_link").all():
            code = pending.data.get("code")
            try:
                fresh = datetime.now(timezone.utc) - datetime.fromisoformat(pending.data["created"]) < LINK_TTL
            except (KeyError, ValueError):
                fresh = False
            if code and fresh and supplied == code:
                sender = message.get("from") or {}
                put(
                    db,
                    "telegram",
                    "telegram",
                    {
                        "chat_id": chat_id,
                        "username": sender.get("username") or sender.get("first_name") or "",
                        "linked_at": now(),
                    },
                    user_id=pending.user_id,
                )
                db.delete(pending)
                db.commit()
                api("sendMessage", chat_id=chat_id, text=f"Linked. {settings.app_name} will send matching jobs here. Use Interested / Skip under each alert.")
                return
    if text.startswith("/start") and user_for_chat(db, chat_id):
        api("sendMessage", chat_id=chat_id, text=f"This chat is linked to {settings.app_name}. Alerts arrive here after each search.")
    # Unknown senders receive no reply at all.


def handle_callback(db, callback):
    chat = str(((callback.get("message") or {}).get("chat") or {}).get("id", ""))
    sender = str((callback.get("from") or {}).get("id", ""))
    if not chat or chat != sender:
        return
    user = user_for_chat(db, chat)
    if not user:
        return
    action, _, job_id = (callback.get("data") or "").partition(":")
    if action not in ("save", "skip"):
        return
    row = db.get(Record, job_id)
    if not row or row.kind != "job" or row.user_id != user.id:
        api("answerCallbackQuery", callback_query_id=callback["id"], text="That job no longer exists.")
        return
    status = "saved" if action == "save" else "skipped"
    put(db, "job", row.key, {**row.data, "status": status, "decided_via": "telegram"}, user_id=user.id)
    api(
        "answerCallbackQuery",
        callback_query_id=callback["id"],
        text=f"Shortlisted. Open {settings.app_name} to prepare documents." if action == "save" else "Skipped.",
    )
    message = callback.get("message") or {}
    if message.get("message_id"):
        try:
            api(
                "editMessageReplyMarkup",
                chat_id=chat,
                message_id=message["message_id"],
                reply_markup={"inline_keyboard": [[{"text": "✓ Shortlisted" if action == "save" else "✗ Skipped", "callback_data": "noop:" + job_id}]]},
            )
        except Exception:
            pass


def handle_update(db, update):
    if update.get("callback_query"):
        handle_callback(db, update["callback_query"])
    elif update.get("message"):
        handle_message(db, update["message"])


def poll_once(offset):
    """One long-poll cycle. Returns the next offset."""
    updates = api(
        "getUpdates",
        http_timeout=40,
        offset=offset,
        limit=50,
        timeout=25,
        allowed_updates=["message", "callback_query"],
    ) or []
    for update in updates:
        try:
            with Session() as db:
                handle_update(db, update)
        except Exception:
            log.exception("Telegram update failed")
        offset = update["update_id"] + 1
    return offset


def poll_forever(stop: threading.Event):
    if not settings.telegram_bot_token:
        return
    with Session() as db:
        offset = int((read(db, "telegram_offset", {}, user_id=SYSTEM) or {}).get("offset") or 0)
    webhook_cleared = False
    while not stop.is_set():
        try:
            new_offset = poll_once(offset)
            if new_offset != offset:
                offset = new_offset
                with Session() as db:
                    put(db, "telegram_offset", "telegram_offset", {"offset": offset}, user_id=SYSTEM)
        except ConflictError:
            if settings.public_https or webhook_cleared:
                log.warning("Telegram webhook is registered; polling disabled.")
                return
            try:
                api("deleteWebhook", http_timeout=15)
                webhook_cleared = True
                continue
            except Exception:
                log.exception("Could not remove Telegram webhook")
                return
        except Exception:
            log.exception("Telegram polling error; retrying in 30s")
            stop.wait(30)
