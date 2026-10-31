"""Growth features: employer featured postings, testimonials, institution
enquiries and member referrals. All system records; the owner moderates them
from the Cohort tab."""

import logging
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from .config import settings
from .db import SYSTEM, Record, put, read, rows, now, delete_row
from . import telemetry

log = logging.getLogger(__name__)
FEATURED_DAYS = 14


def _owner_email():
    return settings.email_to or settings.email_from


def _notify_owner(subject, text):
    from .notifications import email_send

    if settings.smtp_host and settings.email_from and _owner_email():
        try:
            email_send(subject, text, to=_owner_email())
        except Exception as e:
            log.warning("Owner notification failed: %s", type(e).__name__)


# --- employer postings ---------------------------------------------------------------
# Submitted -> the owner reviews -> approved (awaiting payment) -> paid: featured until
# featured_until. Employers follow their listings through employers.py.


def submit_employer_post(db, body):
    post_id = uuid4().hex
    data = {
        "id": post_id,
        "title": body.title.strip(),
        "company": body.company.strip(),
        "location": body.location.strip() or "Not specified",
        "url": body.url.strip(),
        "description": body.description.strip(),
        "deadline": body.deadline,
        "contact_name": body.contact_name.strip(),
        "contact_email": body.contact_email.strip().lower(),
        "note": (body.note or "").strip()[:500],
        "status": "pending",
        "created": now(),
    }
    put(db, "employer_post", "employer_post:" + post_id, data, user_id=SYSTEM)
    telemetry.capture("server_employer_post_submitted", {"company": data["company"]})
    _notify_owner(
        f"{settings.app_name}: featured vacancy request from {data['company']}",
        f"{data['contact_name']} ({data['contact_email']}) submitted \"{data['title']}\" at {data['company']}, {data['location']}.\nDeadline: {data['deadline'] or 'not given'}\nPosting: {data['url']}\n\nNote: {data['note'] or '-'}\n\nReview it in the Cohort tab. Once approved, the employer is emailed a link to pay ({settings.featured_listing_etb} ETB / {settings.featured_listing_usd} USD for {FEATURED_DAYS} days), and the listing goes live when the payment clears.",
    )
    from . import employers

    employers.send_link(
        db,
        data["contact_email"],
        f"{settings.app_name}: we received your vacancy",
        f"Thank you for submitting \"{data['title']}\". We review vacancies within one working day and email you when it is approved; you then pay to feature it, and it goes live as soon as the payment clears.",
    )
    return data


def employer_posts(db, status=None):
    out = [r.data for r in rows(db, "employer_post", user_id=SYSTEM)]
    if status:
        out = [p for p in out if p.get("status") == status]
    return sorted(out, key=lambda p: p.get("created", ""), reverse=True)


def moderate_employer_post(db, post_id, status):
    key = "employer_post:" + post_id
    data = read(db, key, user_id=SYSTEM)
    if not data:
        raise ValueError("Unknown posting.")
    newly_approved = status == "approved" and data.get("status") != "approved"
    data = {**data, "status": status, "moderated": now()}
    put(db, "employer_post", key, data, user_id=SYSTEM)
    if newly_approved and not data.get("featured_until"):
        from . import employers

        data["emailed"] = employers.send_link(
            db,
            data["contact_email"],
            f"{settings.app_name}: your vacancy is approved",
            f"\"{data['title']}\" is approved. Pay {settings.featured_listing_etb:,} ETB or ${settings.featured_listing_usd} to feature it for {FEATURED_DAYS} days at the top of the public listings, in the Telegram digest and in the searches of members it matches. It goes live as soon as the payment clears.",
        )
    return data


def activate_employer_post(db, post_id, ref=None):
    """Feature an approved listing for FEATURED_DAYS, after the current period if it is still running."""
    key = "employer_post:" + post_id
    data = read(db, key, user_id=SYSTEM)
    if not data:
        raise ValueError("Unknown posting.")
    if data.get("status") != "approved":
        raise ValueError("Only approved postings can be featured.")
    start = datetime.now(timezone.utc)
    try:
        start = max(start, datetime.fromisoformat(data.get("featured_until")))
    except (TypeError, ValueError):
        pass
    data = {**data, "featured_until": (start + timedelta(days=FEATURED_DAYS)).isoformat(), "posted": data.get("posted") or now()}
    data["payments"] = [*data.get("payments", []), ref or "owner"]
    put(db, "employer_post", key, data, user_id=SYSTEM)
    from . import public_jobs

    public_jobs.reset_cache()
    return data


def live_employer_posts(db):
    """Approved postings still inside their featured window and before their deadline."""
    today = datetime.now(timezone.utc)
    out = []
    for p in employer_posts(db, "approved"):
        try:
            until = datetime.fromisoformat(p.get("featured_until"))
        except (TypeError, ValueError):
            continue
        if until < today:
            continue
        if p.get("deadline") and p["deadline"][:10] < today.date().isoformat():
            continue
        out.append(p)
    return out


def member_postings(db):
    """Live featured listings as postings for members' searches; keyword screening applies as usual."""
    return [
        {
            "title": p["title"],
            "company": p["company"],
            "location": p.get("location") or "",
            "url": p["url"],
            "description": p["description"],
            "deadline": p.get("deadline"),
            "posted": p.get("posted"),
            "source": "Featured employer",
            "featured_post": p["id"],
        }
        for p in live_employer_posts(db)
    ]


# --- testimonials ----------------------------------------------------------------------


def add_testimonial(db, name, role, quote, organisation=""):
    tid = uuid4().hex
    data = {"id": tid, "name": name.strip()[:120], "role": role.strip()[:160], "organisation": organisation.strip()[:160], "quote": quote.strip()[:600], "created": now()}
    put(db, "testimonial", "testimonial:" + tid, data, user_id=SYSTEM)
    return data


def testimonials(db):
    return sorted((r.data for r in rows(db, "testimonial", user_id=SYSTEM)), key=lambda t: t.get("created", ""))


def delete_testimonial(db, tid):
    row = db.query(Record).filter_by(user_id=SYSTEM, key="testimonial:" + tid).first()
    if not row:
        raise ValueError("Unknown testimonial.")
    delete_row(db, row)


# --- institution enquiries -------------------------------------------------------------


def add_enquiry(db, body):
    eid = uuid4().hex
    data = {
        "id": eid,
        "organisation": body.organisation.strip()[:200],
        "contact_name": body.contact_name.strip()[:120],
        "contact_email": body.contact_email.strip().lower(),
        "seats": body.seats,
        "note": (body.note or "").strip()[:800],
        "status": "new",
        "created": now(),
    }
    put(db, "enquiry", "enquiry:" + eid, data, user_id=SYSTEM)
    telemetry.capture("server_institution_enquiry", {"seats": data["seats"]})
    _notify_owner(
        f"{settings.app_name}: institution enquiry from {data['organisation']}",
        f"{data['contact_name']} ({data['contact_email']}) at {data['organisation']} asks about {data['seats']} seats.\n\n{data['note'] or '-'}\n\nSuggested quote: {data['seats'] * settings.institution_seat_etb} ETB or {data['seats'] * settings.institution_seat_usd} USD per month.",
    )
    return data


def enquiries(db):
    return sorted((r.data for r in rows(db, "enquiry", user_id=SYSTEM)), key=lambda e: e.get("created", ""), reverse=True)


# --- referrals -------------------------------------------------------------------------


def referral_codes(db, user):
    """Each member has a fixed set of personal invitation codes; created on first request."""
    from .auth import create_invites, list_invites
    from .db import User

    note = "referral:" + user.id
    mine = [i for i in list_invites(db) if i.get("note") == note]
    missing = settings.referral_invites - len(mine)
    if missing > 0:
        create_invites(db, missing, note=note)
        mine = [i for i in list_invites(db) if i.get("note") == note]
    base = settings.public_url.rstrip("/") + "/app/?invite="
    out = []
    for i in sorted(mine, key=lambda x: x.get("created", "")):
        joined = db.get(User, i["used_by"]) if i.get("used_by") else None
        out.append({"code": i["code"], "link": base + i["code"], "used": bool(i.get("used_by")), "joined_name": (joined.name or joined.email.split("@")[0]) if joined else None, "joined_at": i.get("used_at")})
    return out


def referred_count(db, user_id):
    from .auth import list_invites

    return sum(1 for i in list_invites(db) if i.get("note") == "referral:" + user_id and i.get("used_by"))
