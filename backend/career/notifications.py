import json
import logging
import ssl
import smtplib
from email.message import EmailMessage
from urllib.parse import quote
import httpx
from sqlalchemy.exc import IntegrityError
from .config import settings
from .db import Record, put, read, now, current_user, current_user_id
from .ai import ai_available, using_server_key
from . import telemetry

INAPP = "inapp"
log = logging.getLogger(__name__)


def describe_failure(e):
    """A log-safe description: exception type and HTTP status only. Provider
    error text can contain request URLs, and Telegram's URL carries the bot
    token, so the raw message is never logged."""
    status = ""
    response = getattr(e, "response", None)
    if response is not None and getattr(response, "status_code", None):
        status = f" HTTP {response.status_code}"
    text = f"{type(e).__name__}{status}"
    for secret in (settings.telegram_bot_token, settings.smtp_password, settings.twilio_auth_token):
        if secret and secret in text:
            text = text.replace(secret, "[redacted]")
    return text


def is_owner():
    return (current_user() or {}).get("role") == "admin"


def telegram_chat(db=None):
    """The linked private chat: the owner's environment value, else the chat
    linked in-app by the scoped user."""
    if is_owner() and settings.telegram_chat_id:
        return settings.telegram_chat_id
    if db is None:
        return ""
    return str((read(db, "telegram", {}) or {}).get("chat_id") or "")


def email_recipient():
    """Alerts go to the account's email; the owner may override with EMAIL_TO."""
    if is_owner() and settings.email_to:
        return settings.email_to
    return (current_user() or {}).get("email") or ""


def availability(db=None):
    user = current_user() or {}
    return {
        "ai": ai_available(),
        "ai_own_key": bool(user.get("openai_key")),
        "ai_sponsored": using_server_key() and user.get("role") != "admin",
        "email": bool(settings.smtp_host and settings.email_from and email_recipient()),
        "telegram": bool(settings.telegram_bot_token and telegram_chat(db)),
        "telegram_bot": bool(settings.telegram_bot_token),
        "whatsapp": is_owner()
        and all(
            [
                settings.twilio_account_sid,
                settings.twilio_auth_token,
                settings.whatsapp_from,
                settings.whatsapp_to,
                settings.whatsapp_content_sid,
            ]
        ),
        "gmail": is_owner()
        and all([settings.gmail_client_id, settings.gmail_client_secret, settings.gmail_refresh_token]),
        "gmail_client": is_owner() and bool(settings.gmail_client_id and settings.gmail_client_secret),
        "imap": bool(user.get("imap")),
        "push": bool(settings.vapid_private_key and settings.vapid_public_key and user.get("push")),
        "push_available": bool(settings.vapid_private_key and settings.vapid_public_key),
        "reliefweb": bool(settings.reliefweb_appname),
        "public_https": settings.public_https,
    }


def job_link(job_id):
    return settings.public_url.rstrip("/") + "/app/?job=" + quote(job_id)


def dashboard_is_public():
    """Only a public HTTPS dashboard is worth linking from a phone or inbox."""
    return settings.public_https


def alert_text(job, match, job_id):
    gaps = "; ".join(match.get("gaps", [])[:3]) or "Review the full eligibility assessment."
    strengths = "; ".join(match.get("strengths", [])[:2])
    lines = [
        f"{job['title']} | {job.get('company') or 'Employer not specified'}",
        job.get("location") or "Location not specified",
        f"Match: {match['score']}/100 ({match.get('mode', 'ai')})",
        match.get("summary", ""),
    ]
    if strengths:
        lines.append("Why you fit: " + strengths)
    lines.append("Gaps / unknowns: " + gaps)
    lines.append("Deadline: " + (job.get("deadline") or "Not specified"))
    if job.get("url"):
        lines.append("Posting: " + job["url"])
    if dashboard_is_public():
        lines.append("Review in " + settings.app_name + ": " + job_link(job_id))
    return "\n".join(lines)


def digest_text(entries):
    lines = [f"{settings.app_name}: {len(entries)} new matching job(s)", ""]
    for n, (job_id, job, match) in enumerate(entries, 1):
        lines.append(f"{n}. {job['title']} | {job.get('company') or 'Employer not specified'} | {job.get('location') or 'Location not specified'}")
        lines.append(f"   Match {match['score']}/100. " + (match.get("summary", "")[:300]))
        strengths = "; ".join(match.get("strengths", [])[:1])
        if strengths:
            lines.append("   Why you fit: " + strengths[:300])
        gaps = "; ".join(match.get("gaps", [])[:2])
        if gaps:
            lines.append("   Gaps / unknowns: " + gaps[:300])
        lines.append("   Deadline: " + (job.get("deadline") or "Not specified"))
        if job.get("url"):
            lines.append("   Posting: " + job["url"])
        if dashboard_is_public():
            lines.append("   Review: " + job_link(job_id))
        lines.append("")
    lines.append("Open " + settings.app_name + " to see the full requirement table and prepare an application.")
    return "\n".join(lines)


def telegram_send(chat_id, text, job_id=None):
    keyboard = []
    if job_id:
        if dashboard_is_public():
            keyboard.append([{"text": "Review job", "url": job_link(job_id)}])
        keyboard.append(
            [
                {"text": "Interested", "callback_data": "save:" + job_id},
                {"text": "Skip", "callback_data": "skip:" + job_id},
            ]
        )
    payload = {"chat_id": chat_id, "text": text[:3900], "disable_web_page_preview": True}
    if keyboard:
        payload["reply_markup"] = {"inline_keyboard": keyboard}
    r = httpx.post(
        f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
        json=payload,
        timeout=30,
    )
    r.raise_for_status()
    if not r.json().get("ok"):
        raise ValueError("Telegram did not accept the message.")


def email_send(subject, text, to=None):
    msg = EmailMessage()
    msg["Subject"] = subject[:180]
    msg["From"] = settings.email_from
    msg["To"] = to or email_recipient()
    msg.set_content(text)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as server:
        server.starttls(context=ssl.create_default_context())
        if settings.smtp_user:
            server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(msg)


def invitation_text(name, code):
    link = settings.public_url.rstrip("/") + "/app/?invite=" + code
    greeting = f"Hello {name.split()[0]}," if name else "Hello,"
    return "\n".join(
        [
            greeting,
            "",
            f"Thank you for requesting an invitation to {settings.app_name}. Your seat is ready.",
            "",
            "Create your account with this personal link (the code is filled in for you):",
            link,
            "",
            f"Your invitation code, if you need to type it: {code}",
            "",
            "Getting started takes about ten minutes:",
            "1. My evidence: upload your CV and verify the facts extracted from it.",
            "2. Job sources: add the suggested boards for your field.",
            "3. Run search: every posting is scored against your verified CV, with the reasons.",
            "4. Account: link Telegram to receive matches as they arrive.",
            "",
            "AI usage is included for the first members, so you do not need your own OpenAI key.",
            "The link is personal; please do not forward it.",
            "",
            "Reply to this email if anything is unclear.",
            "",
            settings.app_name,
            settings.public_url,
        ]
    )


def send_invitation(email, name, code):
    email_send(f"Your invitation to {settings.app_name}", invitation_text(name, code), to=email)


def whatsapp_send(job, match, job_id):
    r = httpx.post(
        f"https://api.twilio.com/2010-04-01/Accounts/{settings.twilio_account_sid}/Messages.json",
        auth=(settings.twilio_account_sid, settings.twilio_auth_token),
        data={
            "From": settings.whatsapp_from,
            "To": settings.whatsapp_to,
            "ContentSid": settings.whatsapp_content_sid,
            "ContentVariables": json.dumps(
                {"1": job["title"], "2": job.get("company", ""), "3": str(match["score"]), "4": job_link(job_id)}
            ),
        },
        timeout=30,
    )
    r.raise_for_status()


def push_send(title, body, url, tag="jfa", db=None):
    """Web push to every device the scoped member subscribed. Dead subscriptions
    (404/410 from the push service) are dropped."""
    from pywebpush import webpush, WebPushException

    subs = list((current_user() or {}).get("push") or [])
    if not subs:
        raise ValueError("No push subscription.")
    payload = json.dumps({"title": title[:120], "body": body[:400], "url": url, "tag": tag})
    keep, sent = [], 0
    for sub in subs:
        try:
            webpush(subscription_info=sub["subscription"], data=payload, vapid_private_key=settings.vapid_private_key, vapid_claims={"sub": settings.vapid_subject or "mailto:" + (settings.email_from or "owner@example.org")}, ttl=86400)
            keep.append(sub)
            sent += 1
        except WebPushException as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status in (404, 410):
                log.info("Dropping expired push subscription (%s)", status)
                continue
            keep.append(sub)
            log.warning("Push not confirmed: %s", describe_failure(e))
    if len(keep) != len(subs):
        _save_push_subscriptions(keep, db)
    if not sent:
        raise ValueError("No device accepted the push.")


def _save_push_subscriptions(subs, db=None):
    from .db import Session, User
    from .auth import seal

    uid = current_user_id()
    own = db is None
    db = db or Session()
    try:
        user = db.get(User, uid) if uid else None
        if user:
            user.secrets = {**(user.secrets or {}), "push": seal(subs) if subs else None}
            db.commit()
        snap = current_user()
        if isinstance(snap, dict):
            snap["push"] = subs
    finally:
        if own:
            db.close()


def send_alert(channel, job, match, job_id, chat_id=""):
    text = alert_text(job, match, job_id)
    if channel == "email":
        email_send(f"{settings.app_name}: " + job["title"][:150], text)
    elif channel == "telegram":
        telegram_send(chat_id, text, job_id)
    elif channel == "whatsapp":
        whatsapp_send(job, match, job_id)
    elif channel == "push":
        score = (match or {}).get("score")
        push_send(f"{score}/100 · {job.get('title', '')}" if score is not None else job.get("title", ""), " · ".join(x for x in (job.get("company"), job.get("location")) if x) or (match or {}).get("summary", ""), job_link(job_id) if dashboard_is_public() else "/app/?job=" + str(job_id), tag="job-" + str(job_id))


def claim(db, job_id, channel, extra=None):
    """Insert the unique alert record before sending. None if already attempted."""
    key = f"alert:{job_id}:{channel}"
    row = Record(
        user_id=current_user_id(),
        kind="alert",
        key=key,
        data={"job_id": job_id, "channel": channel, "status": "sending", "created": now(), **(extra or {})},
    )
    try:
        db.add(row)
        db.commit()
    except IntegrityError:
        db.rollback()
        return None
    return row


def record_inapp(db, job_id, job, match):
    """The in-app inbox entry. Always created, never sent anywhere."""
    row = claim(
        db,
        job_id,
        INAPP,
        {"title": job.get("title"), "company": job.get("company"), "score": match.get("score")},
    )
    if row:
        put(db, "alert", row.key, {**row.data, "status": "unread"})
        return "unread"
    return "already_attempted"


def notify(db, job_id, job, match, channels):
    results = {INAPP: record_inapp(db, job_id, job, match)}
    ready = availability(db)
    chat_id = telegram_chat(db)
    for channel in channels:
        if not ready.get(channel):
            results[channel] = "not_configured"
            continue
        row = claim(db, job_id, channel)
        if row is None:
            results[channel] = "already_attempted"
            continue
        try:
            send_alert(channel, job, match, job_id, chat_id)
            status = "accepted"
        except Exception as e:
            # An HTTP timeout may occur after provider acceptance. Never auto-resend.
            log.warning("Alert via %s not confirmed for job %s: %s", channel, job_id, describe_failure(e))
            status = "delivery_unknown"
        put(db, "alert", row.key, {**row.data, "status": status})
        results[channel] = status
        telemetry.capture("server_alert_delivery", {"channel": channel, "status": status, "digest": False}, distinct_id=current_user_id() or "server")
    return results


def notify_digest(db, entries, channels):
    """One message per channel summarising several jobs. Each job still gets
    its own alert record so it is never announced twice."""
    results = {}
    for job_id, job, match in entries:
        record_inapp(db, job_id, job, match)
    ready = availability(db)
    chat_id = telegram_chat(db)
    for channel in channels:
        if channel == "whatsapp":
            for job_id, job, match in entries:
                results[channel] = notify(db, job_id, job, match, ["whatsapp"])["whatsapp"]
            continue
        if not ready.get(channel):
            results[channel] = "not_configured"
            continue
        rows_ = [claim(db, job_id, channel, {"digest": True}) for job_id, _, _ in entries]
        fresh = [(row, e) for row, e in zip(rows_, entries) if row is not None]
        if not fresh:
            results[channel] = "already_attempted"
            continue
        text = digest_text([e for _, e in fresh])
        try:
            if channel == "email":
                email_send(f"{settings.app_name}: {len(fresh)} new matching jobs", text)
            elif channel == "telegram":
                telegram_send(chat_id, text)
            elif channel == "push":
                push_send(f"{len(fresh)} new matching job{'s' if len(fresh) != 1 else ''}", "; ".join((e[1].get("title") or "")[:60] for e in fresh[:3]), "/app/", tag="digest", db=db)
            status = "accepted"
        except Exception as e:
            log.warning("Digest via %s not confirmed: %s", channel, describe_failure(e))
            status = "delivery_unknown"
        for row, _ in fresh:
            put(db, "alert", row.key, {**row.data, "status": status})
        results[channel] = status
    return results


def test_alert(db, channel):
    """Send a sample message so the owner can confirm a channel works."""
    ready = availability(db)
    if channel == "telegram" and settings.telegram_bot_token and not telegram_chat(db):
        raise ValueError("Link your Telegram chat first (Account → Link Telegram).")
    if not ready.get(channel):
        raise ValueError(f"{channel} is not configured.")
    sample_job = {"title": f"Test alert from {settings.app_name}", "company": "Your workspace", "location": "—", "deadline": None, "url": ""}
    sample_match = {"score": 100, "mode": "test", "summary": "If you can read this, alerts on this channel work.", "gaps": [], "strengths": []}
    text = alert_text(sample_job, sample_match, "test")
    if channel == "email":
        email_send(f"{settings.app_name} test alert", text)
    elif channel == "push":
        push_send(f"Test alert from {settings.app_name}", "If you can read this, push notifications on this device work.", "/app/", tag="test", db=db)
    elif channel == "telegram":
        telegram_send(telegram_chat(db), text)
    elif channel == "whatsapp":
        whatsapp_send(sample_job, sample_match, "test")
    return {"channel": channel, "status": "accepted"}
