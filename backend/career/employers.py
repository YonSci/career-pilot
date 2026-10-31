"""Employer self-service: sign-in by emailed link, listing status, payment and
statistics.

Employers have no password. Their identity is the contact email of the
vacancies they submitted: a sign-in link is only ever sent to that address, and
the session it opens shows only that address's listings. The flow is

    submitted -> owner reviews -> approved, awaiting payment -> paid: live for
    FEATURED_DAYS -> ended (or extended by paying again)

Statistics are counts only: views of the public job page, clicks on Apply
(through /go/<id>), and how many members' keyword screens kept the listing. No
member identity reaches the employer."""

import hashlib
import html
import logging
import secrets
import threading
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from .config import settings
from .db import SYSTEM, Record, put, read, now, delete_row
from . import growth, public_jobs as pj
from .site_stats import is_bot  # noqa: F401 (used by main for listing statistics)

log = logging.getLogger(__name__)
COOKIE = "jfa_employer"
LINK_HOURS = 72
SESSION_DAYS = 30
_stats_lock = threading.Lock()


def site():
    return settings.public_url.rstrip("/")


def _digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _expired(data):
    try:
        return datetime.fromisoformat(data["expires"]) < datetime.now(timezone.utc)
    except (KeyError, TypeError, ValueError):
        return True


def _purge(db, kind):
    for row in db.query(Record).filter_by(user_id=SYSTEM, kind=kind).all():
        if _expired(row.data):
            db.delete(row)
    db.commit()


# --- sign-in ---------------------------------------------------------------------------


def posts_of(db, email):
    email = (email or "").strip().lower()
    return [p for p in growth.employer_posts(db) if p.get("contact_email") == email] if email else []


def login_link(db, email):
    """A single-use sign-in link for this address, valid LINK_HOURS."""
    _purge(db, "employer_token")
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(hours=LINK_HOURS)).isoformat()
    put(db, "employer_token", "employer_token:" + _digest(token), {"email": email.strip().lower(), "expires": expires}, user_id=SYSTEM)
    return site() + "/employers/login?token=" + token


def redeem(db, token):
    """Exchange a sign-in link's token for a session token, or None."""
    row = db.query(Record).filter_by(user_id=SYSTEM, key="employer_token:" + _digest(token or "")).first()
    if not row:
        return None
    data = row.data
    delete_row(db, row)
    if _expired(data):
        return None
    _purge(db, "employer_session")
    session = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)).isoformat()
    put(db, "employer_session", "employer_session:" + _digest(session), {"email": data["email"], "expires": expires}, user_id=SYSTEM)
    return session


def session_email(db, session):
    if not session:
        return None
    data = read(db, "employer_session:" + _digest(session), user_id=SYSTEM)
    return None if not data or _expired(data) else data["email"]


def end_session(db, session):
    row = db.query(Record).filter_by(user_id=SYSTEM, key="employer_session:" + _digest(session or "")).first()
    if row:
        delete_row(db, row)


def can_email():
    return bool(settings.smtp_host and settings.email_from)


def send(to, subject, text):
    """Email an employer. False when email is not configured or fails."""
    from .notifications import email_send

    if not can_email():
        return False
    try:
        email_send(subject, text, to=to)
        return True
    except Exception as e:
        log.warning("Employer email failed: %s", type(e).__name__)
        return False


def send_link(db, email, subject, intro):
    link = login_link(db, email)
    return send(email, subject, f"{intro}\n\nOpen your listings (the link works once and expires in {LINK_HOURS} hours):\n{link}\n\nYou can request a new link at any time at {site()}/employers\n\n{settings.app_name}")


# --- state and statistics --------------------------------------------------------------


def state(post):
    """review, awaiting_payment, live, ended or rejected."""
    status = post.get("status")
    if status == "rejected":
        return "rejected"
    if status != "approved":
        return "review"
    until = post.get("featured_until")
    if not until:
        return "awaiting_payment"
    closed = post.get("deadline") and post["deadline"][:10] < datetime.now(timezone.utc).date().isoformat()
    return "ended" if closed or until < datetime.now(timezone.utc).isoformat() else "live"


def payable(post):
    """Approved and not past its deadline: can be paid for (again)."""
    closed = post.get("deadline") and post["deadline"][:10] < datetime.now(timezone.utc).date().isoformat()
    return post.get("status") == "approved" and not closed


def count(db, post_id, field):
    """Add one to a listing's views, apply_clicks or matches, in total and for today."""
    day = datetime.now(timezone.utc).date().isoformat()
    with _stats_lock:
        key = "listing_stats:" + post_id
        data = read(db, key, {}, user_id=SYSTEM) or {}
        days = data.get("days", {})
        days[day] = {**days.get(day, {}), field: days.get(day, {}).get(field, 0) + 1}
        # Keep 90 days of daily counts; totals stay.
        days = dict(sorted(days.items())[-90:])
        put(db, "listing_stats", key, {**data, field: data.get(field, 0) + 1, "days": days}, user_id=SYSTEM)


def stats(db, post_id):
    data = read(db, "listing_stats:" + post_id, {}, user_id=SYSTEM) or {}
    week = (datetime.now(timezone.utc) - timedelta(days=6)).date().isoformat()
    recent = [v for d, v in data.get("days", {}).items() if d >= week]
    return {
        **{f: data.get(f, 0) for f in ("views", "apply_clicks", "matches")},
        "views_7d": sum(v.get("views", 0) for v in recent),
        "apply_clicks_7d": sum(v.get("apply_clicks", 0) for v in recent),
    }


def public_slug(post):
    return pj.job_slug(post.get("title") or "", post.get("url") or "")


# --- payment -----------------------------------------------------------------------------


def checkout(db, post, currency):
    from . import billing

    if not payable(post):
        raise ValueError("This listing cannot be paid for: it is not approved, or its deadline has passed.")
    payer = SimpleNamespace(id=None, email=post["contact_email"], name=post.get("contact_name") or post.get("company"))
    return billing.start_checkout(db, payer, "featured_listing", currency, extra={"post_id": post["id"]})


# --- pages ---------------------------------------------------------------------------------

CSS = """
.emp{max-width:880px;margin:30px auto}.emp h1{margin:0 0 6px}.emp .who{color:var(--muted);font-size:.9rem;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
.emp form.inline{display:inline}.emp button,.emp .btn2{padding:10px 16px;border-radius:999px;border:none;background:var(--green);color:#fff;font:inherit;font-weight:600;cursor:pointer;text-decoration:none;display:inline-block}
.emp button.plain{background:#fff;color:var(--ink);border:1px solid var(--line)}.emp .note{background:#fff;border:1px solid var(--line);border-left:4px solid var(--green);border-radius:12px;padding:12px 16px;margin:16px 0}
.listing{background:#fff;border:1px solid var(--line);border-radius:16px;padding:18px 20px;margin:14px 0}.listing h2{font-size:1.15rem;margin:0 0 4px}.listing .meta{color:var(--muted);font-size:.88rem}
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:14px 0}.stat{border:1px solid var(--line);border-radius:12px;padding:10px 12px}.stat b{display:block;font-size:1.3rem}.stat small{color:var(--muted);font-size:.76rem}
.pay{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:10px}.state{display:inline-block;font-size:.76rem;font-weight:700;padding:3px 10px;border-radius:999px;background:#eef2ee;color:var(--ink-2)}.state.live{background:var(--green);color:#fff}
.emp label{display:grid;gap:6px;font-weight:600;font-size:.9rem;max-width:420px}.emp input{padding:11px 12px;border:1px solid var(--line);border-radius:10px;font:inherit}
@media(max-width:560px){.stat{padding:8px}.stat b{font-size:1.1rem}.stat small{font-size:.7rem}}
"""

STATE_TEXT = {
    "review": "Waiting for review, usually within one working day.",
    "awaiting_payment": "Approved. Pay to feature it; it goes live as soon as the payment clears.",
    "live": "Live",
    "ended": "Featured period ended",
    "rejected": "Not accepted. Reply to our email if you would like to know why.",
}


def _shell(title, body):
    from . import public_site

    return public_site.shell(title, "Manage your featured vacancies.", f'<style>{CSS}</style><div class="emp">{body}</div>', "/employers", extra_head='<meta name="robots" content="noindex">')


def sign_in_page(message=""):
    note = f'<div class="note">{html.escape(message)}</div>' if message else ""
    return _shell(
        "Employer sign-in",
        "<h1>Your featured vacancies</h1>"
        "<p>Enter the email address you used when submitting a vacancy. We email you a sign-in link; no password needed.</p>"
        f"{note}"
        '<form method="post" action="/employers/link"><label>Email<input type="email" name="email" required autocomplete="email"></label>'
        '<p><button type="submit">Email me a sign-in link</button></p></form>'
        '<p>No vacancy with us yet? <a href="/#employers">Submit one</a>.</p>',
    )


def confirm_page(token):
    # A button, not an automatic redirect: mail scanners that open links must not use up the token.
    return _shell(
        "Employer sign-in",
        "<h1>Sign in</h1><p>Continue to your featured vacancies.</p>"
        f'<form method="post" action="/employers/login"><input type="hidden" name="token" value="{html.escape(token, quote=True)}">'
        '<button type="submit">Open my listings</button></form>',
    )


def _listing(db, post):
    s, st = state(post), stats(db, post["id"])
    price = listing_price()
    label = STATE_TEXT[s]
    if s == "live":
        label = "Live until " + post["featured_until"][:10]
    elif s == "ended" and post.get("featured_until"):
        label = "Featured until " + post["featured_until"][:10] + ", now ended"
    link = f' · <a href="/job/{public_slug(post)}">public page</a>' if s == "live" else ""
    actions = ""
    if payable(post) and s != "review":
        verb = {"awaiting_payment": "Pay", "live": "Extend 14 days:", "ended": "Feature again:"}.get(s, "Pay")
        actions = (
            f'<div class="pay"><span>{verb}</span>'
            f'<form class="inline" method="post" action="/employers/listings/{post["id"]}/checkout"><input type="hidden" name="currency" value="ETB"><button type="submit">{price["etb"]:,} ETB</button></form>'
            f'<form class="inline" method="post" action="/employers/listings/{post["id"]}/checkout"><input type="hidden" name="currency" value="USD"><button type="submit" class="plain">${price["usd"]}</button></form></div>'
        )
    return (
        f'<div class="listing"><span class="state {"live" if s == "live" else ""}">{html.escape(label)}</span>'
        f'<h2>{html.escape(post["title"])}</h2><div class="meta">{html.escape(post["company"])} · {html.escape(post.get("location") or "")}'
        f' · {"closes " + html.escape(post["deadline"][:10]) if post.get("deadline") else "no closing date"}{link}</div>'
        f'<div class="stats"><div class="stat"><b>{st["views"]:,}</b><small>page views ({st["views_7d"]:,} in the last 7 days)</small></div>'
        f'<div class="stat"><b>{st["apply_clicks"]:,}</b><small>clicks on Apply ({st["apply_clicks_7d"]:,} in the last 7 days)</small></div>'
        f'<div class="stat"><b>{st["matches"]:,}</b><small>members whose search matched it</small></div></div>'
        f"{actions}</div>"
    )


def listing_price():
    return {"etb": settings.featured_listing_etb, "usd": settings.featured_listing_usd}


def dashboard_page(db, email, message=""):
    posts = posts_of(db, email)
    note = f'<div class="note">{html.escape(message)}</div>' if message else ""
    listings = "".join(_listing(db, p) for p in posts) or "<p>No vacancies from this address yet.</p>"
    return _shell(
        "Your featured vacancies",
        f'<h1>Your featured vacancies</h1><div class="who">Signed in as {html.escape(email)}'
        '<form class="inline" method="post" action="/employers/logout"><button type="submit" class="plain">Sign out</button></form></div>'
        f"{note}{listings}"
        f'<p>Featuring puts a vacancy at the top of the public listings and in the Telegram digest for {growth.FEATURED_DAYS} days, and sends it to members whose job searches match it. '
        'Statistics count people, not crawlers; members are never identified. <a href="/#employers">Submit another vacancy</a>.</p>',
    )


def manual_page(result):
    return _shell(
        "Payment instructions",
        f'<h1>Payment instructions</h1><div class="note">{html.escape(result["instructions"])}</div><p><a href="/employers/dashboard">Back to your listings</a></p>',
    )
