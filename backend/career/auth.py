"""Accounts, sessions, invites, secret sealing and plan entitlements."""

import base64
import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime, timezone, timedelta
from cryptography.fernet import Fernet, InvalidToken
from .config import settings
from .db import Session, User, Record, SYSTEM, LEGACY, put, read, rows, now

SESSION_COOKIE = "cp_session"
SESSION_DAYS = 30
CSRF_HEADER = "x-requested-with"

# Plan entitlements. Invitees pay for their own AI usage (bring your own key),
# so the beta plan is generous; free is a taste; pro is reserved for billing.
PLANS = {
    "free": {"label": "Free", "sources": 2, "evaluations_per_run": 10, "packages_per_month": 1, "schedule": False},
    "beta": {"label": "Beta", "sources": 20, "evaluations_per_run": 50, "packages_per_month": 30, "schedule": True},
    "pro": {"label": "Pro", "sources": 50, "evaluations_per_run": 50, "packages_per_month": 60, "schedule": True},
}


def plan_limits(plan):
    return PLANS.get(plan) or PLANS["free"]


# --- passwords --------------------------------------------------------------------


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, salt, digest = stored.split("$")
        if algo != "scrypt":
            return False
        candidate = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=2**14, r=8, p=1)
        return hmac.compare_digest(candidate, base64.b64decode(digest))
    except (ValueError, TypeError):
        return False


def validate_password(password: str):
    if len(password) < 10:
        raise ValueError("Use a password of at least 10 characters.")


# --- sealed secrets ---------------------------------------------------------------


def _fernet():
    material = settings.secret_key or settings.app_token
    key = base64.urlsafe_b64encode(hashlib.sha256(("career-pilot-secrets:" + material).encode()).digest())
    return Fernet(key)


def seal(value):
    """Encrypt a string or JSON-serialisable value for storage. None stays None."""
    if value in (None, ""):
        return None
    return _fernet().encrypt(json.dumps(value).encode()).decode()


def unseal(token):
    if not token:
        return None
    try:
        return json.loads(_fernet().decrypt(token.encode()).decode())
    except (InvalidToken, ValueError):
        return None


# --- sessions ---------------------------------------------------------------------


def create_session(db, user: User, user_agent=""):
    token = secrets.token_urlsafe(32)
    put(
        db,
        "session",
        "session:" + hashlib.sha256(token.encode()).hexdigest(),
        {"created": now(), "user_agent": user_agent[:200]},
        user_id=user.id,
    )
    return token


def session_user(db, token):
    if not token:
        return None
    key = "session:" + hashlib.sha256(token.encode()).hexdigest()
    row = db.query(Record).filter_by(key=key, kind="session").first()
    if not row:
        return None
    created = datetime.fromisoformat(row.data.get("created", now()))
    if datetime.now(timezone.utc) - created > timedelta(days=SESSION_DAYS):
        db.delete(row)
        db.commit()
        return None
    return db.get(User, row.user_id)


def destroy_session(db, token):
    if not token:
        return
    key = "session:" + hashlib.sha256(token.encode()).hexdigest()
    row = db.query(Record).filter_by(key=key, kind="session").first()
    if row:
        db.delete(row)
        db.commit()


def touch(db, user: User):
    """Record activity at most every ten minutes."""
    try:
        last = datetime.fromisoformat(user.last_active)
    except (TypeError, ValueError):
        last = datetime.fromtimestamp(0, timezone.utc)
    if datetime.now(timezone.utc) - last > timedelta(minutes=10):
        user.last_active = now()
        db.commit()


# --- invites and registration ------------------------------------------------------


def create_invites(db, count=1, note=""):
    codes = []
    for _ in range(max(1, min(count, 50))):
        code = secrets.token_urlsafe(6).replace("-", "x").replace("_", "y")
        put(db, "invite", "invite:" + code, {"code": code, "note": note, "created": now(), "used_by": None}, user_id=SYSTEM)
        codes.append(code)
    return codes


def list_invites(db):
    return [r.data for r in rows(db, "invite", user_id=SYSTEM)]


def admin_user(db):
    return db.query(User).filter_by(role="admin").order_by(User.created).first()


def register(db, email, password, name="", invite=None):
    email = (email or "").strip().lower()
    if "@" not in email or len(email) > 320:
        raise ValueError("Enter a valid email address.")
    validate_password(password or "")
    if db.query(User).filter_by(email=email).first():
        raise ValueError("An account with this email already exists. Sign in instead.")
    first = db.query(User).count() == 0
    invite_row = None
    if not first and settings.invite_only:
        code = (invite or "").strip()
        invite_row = db.query(Record).filter_by(user_id=SYSTEM, key="invite:" + code).first() if code else None
        if not invite_row or invite_row.data.get("used_by"):
            raise ValueError("A valid invite code is required during the beta.")
    user = User(
        email=email,
        name=(name or "").strip()[:200],
        password_hash=hash_password(password),
        role="admin" if first else "member",
        plan="beta",
    )
    db.add(user)
    db.commit()
    if first:
        claim_legacy_records(db, user)
    if invite_row:
        put(db, "invite", invite_row.key, {**invite_row.data, "used_by": user.id, "used_at": now()}, user_id=SYSTEM)
    return user


def claim_legacy_records(db, user: User):
    """Records created before accounts existed belong to the first admin."""
    changed = 0
    for row in db.query(Record).filter_by(user_id=LEGACY).all():
        row.user_id = user.id
        changed += 1
    db.commit()
    return changed


def authenticate(db, email, password):
    email = (email or "").strip().lower()
    user = db.query(User).filter_by(email=email).first()
    if not user or not verify_password(password or "", user.password_hash):
        return None
    return user


# --- login throttling ---------------------------------------------------------------

_attempts: dict[str, list[float]] = {}


def throttle(key: str, limit=8, window=900):
    """Raise ValueError when `key` has exceeded `limit` attempts in `window` seconds."""
    stamp = time.time()
    recent = [t for t in _attempts.get(key, []) if stamp - t < window]
    if len(recent) >= limit:
        raise ValueError("Too many attempts. Try again in a few minutes.")
    recent.append(stamp)
    _attempts[key] = recent


# --- usage metrics for the admin view ------------------------------------------------


def user_metrics(db, user: User):
    profile = read(db, "profile", {}, user_id=user.id) or {}
    verified = sum(1 for f in profile.get("facts", []) if f.get("verified"))
    sources = rows(db, "source", user_id=user.id)
    runs = rows(db, "run", user_id=user.id)
    apps = rows(db, "application", user_id=user.id)
    jobs = rows(db, "job", user_id=user.id)
    telegram = read(db, "telegram", {}, user_id=user.id) or {}
    return {
        **user.public(),
        "verified_facts": verified,
        "sources": len(sources),
        "searches": len(runs),
        "jobs": len(jobs),
        "evaluated": sum(1 for j in jobs if j.data.get("match")),
        "packages": sum(1 for a in apps if a.data.get("package")),
        "packages_requested": len(apps),
        "telegram_linked": bool(telegram.get("chat_id")),
        "activated": verified > 0 and len(sources) > 0,
        "drafted": any(a.data.get("package") for a in apps),
    }


def packages_this_month(db):
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    return sum(1 for a in rows(db, "application") if (a.data.get("approved_at") or "").startswith(month))
