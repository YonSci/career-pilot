import hashlib
import hmac
import logging
import json
import secrets as pysecrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from typing import Literal
from fastapi import (
    FastAPI,
    Depends,
    HTTPException,
    Request,
    Response,
    UploadFile,
    File,
    BackgroundTasks,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response as RawResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from .config import settings
from .db import (
    SYSTEM,
    Session,
    Record,
    User,
    engine,
    initialize,
    read,
    put,
    rows,
    find,
    get_row,
    now,
    set_scope,
    user_snapshot,
    current_user,
)
from . import auth as accounts
from .schemas import Profile, Preferences, JobInput, SourceInput, Package, MATCH_RELEVANT_PREFERENCES
from .documents import extract_text, package_zip
from .ai import extract_profile, ai_available, verify_key
from .sources import validate_source, collect, Context, SUGGESTED_SOURCES, KIND_LABELS, imap_check
from .service import ingest, evaluate, expired, prepare_application, run_scan
from .notifications import availability, test_alert, send_invitation
from .scheduler import scheduler
from . import telegram
from . import assistant
from . import telemetry
from . import public_jobs
from . import billing
from . import growth
from . import channel
from .ai import server_key_usage


@asynccontextmanager
async def lifespan(app):
    if len(settings.app_token) < 24:
        raise RuntimeError(
            "Set APP_TOKEN to a random secret of at least 24 characters before starting."
        )
    initialize()
    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown()


VERSION = "0.4.0"
app = FastAPI(title=settings.app_name, version=VERSION, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[s.strip() for s in settings.cors_origins.split(",") if s.strip()],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
)


@app.middleware("http")
async def private_responses(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["X-Frame-Options"] = "DENY"
    return response


def db_session():
    with Session() as db:
        yield db


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    """Unexpected errors: logged, reported to telemetry, and answered with a generic message."""
    logging.getLogger(__name__).exception("Unhandled error on %s %s", request.method, request.url.path)
    telemetry.capture_exception(exc, where=request.url.path)
    return JSONResponse({"detail": "Something went wrong on the server. Please try again."}, status_code=500)


def ai_action(user: User, action: str):
    """Per-account hourly limit on manual actions that call the model."""
    try:
        accounts.throttle(f"ai:{user.id}", limit=settings.ai_actions_per_hour, window=3600)
    except ValueError:
        raise HTTPException(429, f"Too many AI requests in the last hour ({action}). Please wait a while.")


# --- authentication -------------------------------------------------------------------


def set_session_cookie(response: Response, token: str):
    response.set_cookie(
        accounts.SESSION_COOKIE,
        token,
        max_age=accounts.SESSION_DAYS * 86400,
        httponly=True,
        samesite="lax",
        secure=settings.public_https,
        path="/",
    )


async def auth(request: Request, db=Depends(db_session)) -> User:
    """Resolve the signed-in user (session cookie) or the owner (APP_TOKEN
    bearer, for scripts) and enter their scope for this request."""
    bearer = request.headers.get("authorization", "").removeprefix("Bearer ")
    user = None
    if bearer and settings.app_token and hmac.compare_digest(bearer, settings.app_token):
        user = accounts.admin_user(db)
        if not user:
            raise HTTPException(401, "Create the first (owner) account in the dashboard, then retry.")
    else:
        token = request.cookies.get(accounts.SESSION_COOKIE)
        user = accounts.session_user(db, token)
        if not user:
            raise HTTPException(401, "Sign in to continue.")
        if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get(accounts.CSRF_HEADER, "").lower() != "careerpilot":
            raise HTTPException(403, "Cross-site request rejected.")
    accounts.touch(db, user)
    set_scope(user_snapshot(user))
    return user


async def admin(user: User = Depends(auth)) -> User:
    if user.role != "admin":
        raise HTTPException(403, "Owner access only.")
    return user


def row_or_404(db, id, kind):
    row = get_row(db, id, kind)
    if not row:
        raise HTTPException(404, "Record not found.")
    return row


def item(row):
    return {"id": row.id, **row.data, "updated": row.updated}


def job_summary(row):
    """List view of a posting: everything except the full description."""
    data = {k: v for k, v in row.data.items() if k not in ("description", "body_hash", "screen")}
    description = row.data.get("description") or ""
    return {
        "id": row.id,
        **data,
        "description_preview": description[:280],
        "expired": expired(row.data),
        "updated": row.updated,
    }


@app.get("/health")
def health():
    return {"status": "ok", "service": settings.app_name, "version": VERSION}


@app.get("/api/setup")
def setup(db=Depends(db_session)):
    """Public: what the sign-in screen needs to know."""
    return {
        "app_name": settings.app_name,
        "needs_first_account": db.query(User).count() == 0,
        "invite_only": settings.invite_only,
        "owner_email_fixed": bool(settings.owner_email),
        "sponsored_seats_left": max(0, settings.sponsored_seats - accounts.sponsored_count(db)) if settings.openai_api_key else 0,
        "analytics": (
            {"provider": "posthog", "key": settings.posthog_key, "host": settings.posthog_host, "replay": settings.posthog_replay}
            if settings.posthog_key
            else None
        ),
    }


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=40)


@app.post("/api/assistant/chat")
async def assistant_chat(body: ChatRequest, request: Request, db=Depends(db_session)):
    """Public platform assistant. Signed-in members get answers tailored to a
    short, non-sensitive status summary of their workspace."""
    ip = request.client.host if request.client else "?"
    try:
        accounts.throttle("assistant:" + ip, limit=30, window=3600)
    except ValueError as e:
        raise HTTPException(429, str(e))
    status = None
    user = accounts.session_user(db, request.cookies.get(accounts.SESSION_COOKIE))
    if user:
        set_scope(user_snapshot(user))
        profile = read(db, "profile", {}) or {}
        status = {
            "signed in": "yes",
            "plan": user.plan,
            "openai key set": "yes" if ai_available() else "no",
            "verified CV facts": sum(1 for f in profile.get("facts", []) if f.get("verified")),
            "job sources": len(rows(db, "source")),
            "searches run": len(rows(db, "run")),
            "postings in workspace": len(rows(db, "job")),
            "applications prepared": sum(1 for a in rows(db, "application") if a.data.get("package")),
            "telegram linked": "yes" if telegram.link_status(db)["linked"] else "no",
            "scheduled searches": "on" if (read(db, "schedule", {}) or {}).get("enabled") else "off",
        }
    try:
        reply = await run_in_threadpool(assistant.answer, [m.model_dump() for m in body.messages], status)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except Exception:
        raise HTTPException(502, "The assistant could not answer right now. Please try again in a moment.")
    return {"reply": reply, "available": assistant.available()}


@app.get("/api/assistant/suggestions")
def assistant_suggestions():
    return {"questions": assistant.SUGGESTED_QUESTIONS, "available": assistant.available()}


_stats_cache = {"at": 0.0, "value": None}


@app.get("/api/public/stats")
def public_stats(db=Depends(db_session)):
    """Aggregate, anonymous usage numbers for the landing page (cached 10 minutes)."""
    import time as _time

    if _stats_cache["value"] and _time.time() - _stats_cache["at"] < 600:
        return _stats_cache["value"]
    jobs = db.query(Record).filter_by(kind="job").all()
    apps = db.query(Record).filter_by(kind="application").all()
    value = {
        "accounts": db.query(User).count(),
        "postings_screened": len(jobs),
        "evaluated": sum(1 for j in jobs if j.data.get("match")),
        "strong_matches": sum(1 for j in jobs if (j.data.get("match") or {}).get("score", 0) >= 70),
        "applications_drafted": sum(1 for a in apps if a.data.get("package")),
        "sources": db.query(Record).filter_by(kind="source").count(),
    }
    _stats_cache.update(at=_time.time(), value=value)
    return value


@app.get("/api/public/jobs")
def public_job_listings(db=Depends(db_session)):
    """Latest, featured and closing-soon postings from public boards for the landing page.
    Public posting facts only; nothing about members. Cached 10 minutes."""
    return public_jobs.public_view(public_jobs.listings(db))


@app.get("/api/public/pricing")
def public_pricing():
    return billing.catalog()


@app.get("/api/public/testimonials")
def public_testimonials(db=Depends(db_session)):
    return {"testimonials": [{k: t.get(k) for k in ("name", "role", "organisation", "quote")} for t in growth.testimonials(db)]}


class EmployerPost(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    company: str = Field(min_length=2, max_length=200)
    location: str = Field(default="", max_length=200)
    url: str = Field(min_length=8, max_length=2000)
    description: str = Field(min_length=80, max_length=20000)
    deadline: str | None = Field(default=None, max_length=10)
    contact_name: str = Field(min_length=2, max_length=120)
    contact_email: str = Field(min_length=5, max_length=320)
    note: str = Field(default="", max_length=500)


@app.post("/api/employers/post")
def employer_post(body: EmployerPost, request: Request, db=Depends(db_session)):
    """Employers submit a vacancy for a featured slot; the owner approves it after payment."""
    if "@" not in body.contact_email or not body.url.lower().startswith(("http://", "https://")):
        raise HTTPException(422, "Enter a valid contact email and a full posting link.")
    try:
        accounts.throttle("employer:" + (request.client.host if request.client else "?"), limit=5, window=3600)
    except ValueError as e:
        raise HTTPException(429, str(e))
    post = growth.submit_employer_post(db, body)
    return {"status": "received", "id": post["id"]}


class Enquiry(BaseModel):
    organisation: str = Field(min_length=2, max_length=200)
    contact_name: str = Field(min_length=2, max_length=120)
    contact_email: str = Field(min_length=5, max_length=320)
    seats: int = Field(default=25, ge=1, le=100000)
    note: str = Field(default="", max_length=800)


@app.post("/api/institutions/enquiry")
def institution_enquiry(body: Enquiry, request: Request, db=Depends(db_session)):
    if "@" not in body.contact_email:
        raise HTTPException(422, "Enter a valid contact email.")
    try:
        accounts.throttle("enquiry:" + (request.client.host if request.client else "?"), limit=5, window=3600)
    except ValueError as e:
        raise HTTPException(429, str(e))
    growth.add_enquiry(db, body)
    return {"status": "received"}


@app.get("/jobs", include_in_schema=False)
@app.get("/jobs/{sector}", include_in_schema=False)
def sector_jobs_page(sector: str | None = None, db=Depends(db_session)):
    page = public_jobs.sector_page(public_jobs.listings(db), sector)
    if page is None:
        raise HTTPException(404, "Not found")
    return HTMLResponse(page)


@app.get("/sitemap.xml", include_in_schema=False)
def sitemap_xml(db=Depends(db_session)):
    return RawResponse(public_jobs.sitemap(public_jobs.listings(db)), media_type="application/xml")


@app.get("/robots.txt", include_in_schema=False)
def robots_txt():
    return RawResponse(f"User-agent: *\nAllow: /\nDisallow: /app/\nDisallow: /api/\nSitemap: {settings.public_url.rstrip('/')}/sitemap.xml\n", media_type="text/plain")


# --- billing ------------------------------------------------------------------------


class CheckoutRequest(BaseModel):
    product: Literal["pro", "pro_plus", "package", "package_5"]
    currency: Literal["ETB", "USD"] = "ETB"


@app.get("/api/billing")
def billing_status(user: User = Depends(auth), db=Depends(db_session)):
    return {**billing.catalog(), **billing.plan_status(user), "payments": [{k: p.get(k) for k in ("ref", "product", "amount", "currency", "provider", "status", "created", "paid_at")} for p in billing.payments(db, user.id)][:20]}


@app.post("/api/billing/checkout")
def billing_checkout(body: CheckoutRequest, user: User = Depends(auth), db=Depends(db_session)):
    try:
        accounts.throttle(f"checkout:{user.id}", limit=10, window=3600)
        return billing.start_checkout(db, user, body.product, body.currency)
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.get("/api/billing/return", include_in_schema=False)
def billing_return(ref: str = "", db=Depends(db_session)):
    """Where Chapa sends the member back. Verifies server-side, then opens the dashboard."""
    from fastapi.responses import RedirectResponse

    status = "unknown"
    if ref and settings.chapa_secret_key:
        try:
            status = billing.chapa_verify(db, ref).get("status", "unknown")
        except Exception as e:
            logging.getLogger(__name__).warning("Chapa verify failed for %s: %s", ref, type(e).__name__)
    return RedirectResponse(settings.public_url.rstrip("/") + "/app/?payment=" + status, status_code=303)


@app.post("/api/billing/webhook/chapa", include_in_schema=False)
async def chapa_webhook(request: Request, db=Depends(db_session)):
    raw = await request.body()
    signature = request.headers.get("x-chapa-signature") or request.headers.get("chapa-signature") or ""
    try:
        billing.chapa_webhook(db, raw, signature)
    except PermissionError:
        raise HTTPException(401, "Bad signature.")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.post("/api/billing/webhook/lemonsqueezy", include_in_schema=False)
async def lemon_webhook(request: Request, db=Depends(db_session)):
    raw = await request.body()
    try:
        billing.lemon_webhook(db, raw, request.headers.get("x-signature", ""))
    except PermissionError:
        raise HTTPException(401, "Bad signature.")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.post("/api/admin/payments/{ref}/paid")
def admin_mark_paid(ref: str, _: User = Depends(admin), db=Depends(db_session)):
    try:
        return billing.apply_purchase(db, ref, provider_ref="manual")
    except ValueError as e:
        raise HTTPException(404, str(e))


# --- growth: owner moderation, referrals, channel ---------------------------------------


class Moderation(BaseModel):
    status: Literal["approved", "rejected", "pending"]


@app.put("/api/admin/employer-posts/{id}")
def admin_moderate_post(id: str, body: Moderation, _: User = Depends(admin), db=Depends(db_session)):
    try:
        post = growth.moderate_employer_post(db, id, body.status)
    except ValueError as e:
        raise HTTPException(404, str(e))
    public_jobs.reset_cache()
    _landing_cache.update(at=0.0, html=None)
    return post


class TestimonialInput(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    role: str = Field(default="", max_length=160)
    organisation: str = Field(default="", max_length=160)
    quote: str = Field(min_length=10, max_length=600)


@app.post("/api/admin/testimonials")
def admin_add_testimonial(body: TestimonialInput, _: User = Depends(admin), db=Depends(db_session)):
    return growth.add_testimonial(db, body.name, body.role, body.quote, body.organisation)


@app.delete("/api/admin/testimonials/{id}")
def admin_delete_testimonial(id: str, _: User = Depends(admin), db=Depends(db_session)):
    try:
        growth.delete_testimonial(db, id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"deleted": True}


@app.get("/api/account/referrals")
def account_referrals(user: User = Depends(auth), db=Depends(db_session)):
    return {"invites": growth.referral_codes(db, user), "referred": growth.referred_count(db, user.id)}


class ChannelPost(BaseModel):
    kind: Literal["daily", "weekly"] = "daily"


@app.post("/api/admin/channel/post")
def admin_channel_post(body: ChannelPost, _: User = Depends(admin), db=Depends(db_session)):
    try:
        return channel.post(body.kind, db)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except Exception as e:
        raise HTTPException(502, f"Telegram refused the post ({type(e).__name__}).")


_landing_cache = {"at": 0.0, "html": None}


@app.get("/", include_in_schema=False)
def landing_page(db=Depends(db_session)):
    """The landing page with the latest public postings rendered in (search engines
    see them without JavaScript), plus JobPosting structured data."""
    import time as _time

    index = settings.landing_dir / "index.html"
    if not index.is_file():
        raise HTTPException(404, "Not found")
    if _landing_cache["html"] and _time.time() - _landing_cache["at"] < 600:
        return HTMLResponse(_landing_cache["html"])
    data = public_jobs.listings(db)
    page = index.read_text(encoding="utf-8")
    if settings.google_site_verification:
        import html as _h

        tag = '<meta name="google-site-verification" content="' + _h.escape(settings.google_site_verification.strip(), quote=True) + '" />'
        page = page.replace('<meta charset="utf-8" />', '<meta charset="utf-8" />' + chr(10) + tag, 1)
    page = page.replace("<!--JOBS-->", public_jobs.render_cards(data["latest"]), 1)
    page = page.replace("<!--JOBS-JSONLD-->", public_jobs.json_ld(data["latest"], settings.public_url.rstrip("/") + "/#jobs"), 1)
    quotes = growth.testimonials(db)
    if quotes:
        import html as _html

        cards = "".join(f'<div class="quote"><p>“{_html.escape(t["quote"])}”</p><b>{_html.escape(t["name"])}</b><small>{_html.escape(", ".join(x for x in (t.get("role"), t.get("organisation")) if x))}</small></div>' for t in quotes[:6])
        page = page.replace('<section id="testimonials" class="wrap reveal" hidden>', '<section id="testimonials" class="wrap reveal">', 1).replace("<!--TESTIMONIALS-->", cards, 1)
    _landing_cache.update(at=_time.time(), html=page)
    return HTMLResponse(page)


class WaitlistRequest(BaseModel):
    email: str = Field(max_length=320)
    name: str = Field(default="", max_length=200)
    note: str = Field(default="", max_length=500)


@app.post("/api/waitlist")
def waitlist(body: WaitlistRequest, request: Request, db=Depends(db_session)):
    """Public: invitation requests from the landing page."""
    try:
        accounts.throttle("waitlist:" + (request.client.host if request.client else "?"), limit=5, window=3600)
        accounts.add_waitlist(db, body.email, body.name, body.note)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"ok": True}


class Credentials(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=200)
    name: str = Field(default="", max_length=200)
    invite: str = Field(default="", max_length=64)


@app.post("/api/auth/signup")
def signup(body: Credentials, request: Request, response: Response, db=Depends(db_session)):
    try:
        accounts.throttle("signup:" + (request.client.host if request.client else "?"), limit=10)
        user = accounts.register(db, body.email, body.password, body.name, body.invite)
    except ValueError as e:
        raise HTTPException(422, str(e))
    set_session_cookie(response, accounts.create_session(db, user, request.headers.get("user-agent", "")))
    return user.public()


@app.post("/api/auth/login")
def login(body: Credentials, request: Request, response: Response, db=Depends(db_session)):
    try:
        accounts.throttle("login:" + body.email.strip().lower())
        accounts.throttle("login-ip:" + (request.client.host if request.client else "?"), limit=30)
    except ValueError as e:
        raise HTTPException(429, str(e))
    user = accounts.authenticate(db, body.email, body.password)
    if not user:
        raise HTTPException(401, "Email or password is incorrect.")
    set_session_cookie(response, accounts.create_session(db, user, request.headers.get("user-agent", "")))
    return user.public()


@app.post("/api/auth/logout")
def logout(request: Request, response: Response, db=Depends(db_session)):
    accounts.destroy_session(db, request.cookies.get(accounts.SESSION_COOKIE))
    response.delete_cookie(accounts.SESSION_COOKIE, path="/")
    return {"ok": True}


@app.get("/api/auth/me")
def me(user: User = Depends(auth)):
    return user.public()


# --- account settings ----------------------------------------------------------------


class AccountEdit(BaseModel):
    name: str = Field(default="", max_length=200)


@app.put("/api/account", )
def edit_account(body: AccountEdit, user: User = Depends(auth), db=Depends(db_session)):
    user.name = body.name.strip()
    db.commit()
    return user.public()


class PasswordChange(BaseModel):
    current: str = Field(max_length=200)
    new: str = Field(max_length=200)


@app.put("/api/account/password")
def change_password(body: PasswordChange, request: Request, user: User = Depends(auth), db=Depends(db_session)):
    if not accounts.verify_password(body.current, user.password_hash):
        raise HTTPException(422, "The current password is incorrect.")
    try:
        accounts.validate_password(body.new)
    except ValueError as e:
        raise HTTPException(422, str(e))
    user.password_hash = accounts.hash_password(body.new)
    db.commit()
    accounts.destroy_user_sessions(db, user.id, keep_token=request.cookies.get(accounts.SESSION_COOKIE))
    return {"ok": True}


class KeyInput(BaseModel):
    key: str = Field(min_length=20, max_length=300)


@app.put("/api/account/openai_key")
async def set_openai_key(body: KeyInput, user: User = Depends(auth), db=Depends(db_session)):
    key = body.key.strip()
    try:
        await run_in_threadpool(verify_key, key)
    except Exception as e:
        raise HTTPException(422, f"OpenAI rejected this key or the configured models are not available to it ({type(e).__name__}).")
    user.secrets = {**(user.secrets or {}), "openai_key": accounts.seal(key)}
    db.commit()
    return user.public()


@app.delete("/api/account/openai_key")
def remove_openai_key(user: User = Depends(auth), db=Depends(db_session)):
    user.secrets = {k: v for k, v in (user.secrets or {}).items() if k != "openai_key"}
    db.commit()
    return user.public()


class ImapInput(BaseModel):
    host: str = Field(min_length=3, max_length=200)
    port: int = Field(default=993, ge=1, le=65535)
    username: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=200)
    folder: str = Field(default="JobsFindAI", max_length=100)


@app.put("/api/account/imap")
async def set_imap(body: ImapInput, user: User = Depends(auth), db=Depends(db_session)):
    creds = body.model_dump()
    creds["host"] = creds["host"].strip().lower()
    creds["username"] = creds["username"].strip()
    creds["folder"] = creds["folder"].strip() or "JobsFindAI"
    try:
        count = await run_in_threadpool(imap_check, creds)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except Exception as e:
        raise HTTPException(422, f"Could not reach the mailbox ({type(e).__name__}). Check the host and port.")
    user.secrets = {**(user.secrets or {}), "imap": accounts.seal(creds)}
    db.commit()
    return {**user.public(), "messages_in_folder": count}


@app.delete("/api/account/imap")
def remove_imap(user: User = Depends(auth), db=Depends(db_session)):
    user.secrets = {k: v for k, v in (user.secrets or {}).items() if k != "imap"}
    db.commit()
    return user.public()


# --- admin -----------------------------------------------------------------------------


@app.get("/api/admin/overview")
def admin_overview(_: User = Depends(admin), db=Depends(db_session)):
    users = db.query(User).order_by(User.created).all()
    metrics = [accounts.user_metrics(db, u) for u in users]
    return {
        "users": metrics,
        "invites": accounts.list_invites(db),
        "waitlist": accounts.list_waitlist(db),
        "employer_posts": growth.employer_posts(db),
        "testimonials": growth.testimonials(db),
        "enquiries": growth.enquiries(db),
        "payments": billing.payments(db)[:50],
        "pricing": billing.catalog(),
        "channel": {"enabled": channel.enabled(), **{k: v for k, v in channel.state(db).items() if k != "posted"}},
        "totals": {
            "users": len(users),
            "activated": sum(1 for m in metrics if m["activated"]),
            "drafted": sum(1 for m in metrics if m["drafted"]),
            "with_key": sum(1 for m in metrics if m["has_openai_key"]),
            "telegram": sum(1 for m in metrics if m["telegram_linked"]),
            "sponsored": sum(1 for m in metrics if m["sponsored"]),
            "sponsored_seats": settings.sponsored_seats if settings.openai_api_key else 0,
            "server_key_calls_this_month": server_key_usage().get("calls", 0),
            "server_key_monthly_cap": settings.server_key_monthly_calls,
            "sponsored_evaluations_this_month": sum(m["evaluations_this_month"] for m in metrics if m["sponsored"] and not m["has_openai_key"]),
        },
        "plans": accounts.PLANS,
    }


class InviteRequest(BaseModel):
    count: int = Field(default=1, ge=1, le=50)
    note: str = Field(default="", max_length=200)


@app.post("/api/admin/invites")
def admin_invites(body: InviteRequest, _: User = Depends(admin), db=Depends(db_session)):
    return {"codes": accounts.create_invites(db, body.count, body.note)}


class WaitlistInvite(BaseModel):
    emails: list[str] = Field(min_length=1, max_length=50)


@app.post("/api/admin/waitlist/invite")
def admin_invite_waitlist(body: WaitlistInvite, _: User = Depends(admin), db=Depends(db_session)):
    """Create a personal invite code for each address and email the sign-up link.
    Addresses not on the waitlist are added to it. Existing accounts are skipped.
    When email is not configured the code is still created and returned for sharing by hand."""
    results = []
    mailer = bool(settings.smtp_host and settings.email_from)
    for raw in body.emails:
        email = (raw or "").strip().lower()
        if "@" not in email or len(email) > 320:
            results.append({"email": raw, "status": "invalid"})
            continue
        if db.query(User).filter_by(email=email).first():
            results.append({"email": email, "status": "already_registered"})
            continue
        entry = read(db, "waitlist:" + email, user_id=SYSTEM) or {}
        code = entry.get("code") if entry.get("invited") and entry.get("code") else accounts.create_invites(db, 1, note=email)[0]
        entry = accounts.mark_invited(db, email, code)
        status = "code_only"
        if mailer:
            try:
                send_invitation(email, entry.get("name", ""), code)
                status = "sent"
            except Exception as e:
                logging.getLogger(__name__).warning("Invitation email to %s failed: %s", email, type(e).__name__)
                status = "email_failed"
        results.append({"email": email, "status": status, "code": code, "link": settings.public_url.rstrip("/") + "/app/?invite=" + code})
    return {"results": results, "email_configured": mailer}


class UserEdit(BaseModel):
    plan: Literal["free", "beta", "sponsored", "pro", "pro_plus"] | None = None
    role: Literal["admin", "member"] | None = None
    sponsored: bool | None = None
    # Institution or cohort the member belongs to (group analytics); empty clears it.
    organisation: str | None = Field(default=None, max_length=80)


@app.put("/api/admin/users/{id}")
def admin_edit_user(id: str, body: UserEdit, me: User = Depends(admin), db=Depends(db_session)):
    user = db.get(User, id)
    if not user:
        raise HTTPException(404, "User not found.")
    if body.sponsored is not None:
        accounts.set_sponsored(db, user, body.sponsored)
    if body.organisation is not None:
        user.settings = {**(user.settings or {}), "organisation": body.organisation.strip()}
    if body.plan:
        user.plan = body.plan
    if body.role:
        if user.id == me.id and body.role != "admin":
            raise HTTPException(422, "You cannot remove your own owner role.")
        user.role = body.role
    db.commit()
    return accounts.user_metrics(db, user)


@app.post("/api/admin/users/{id}/reset")
def admin_reset_password(id: str, _: User = Depends(admin), db=Depends(db_session)):
    user = db.get(User, id)
    if not user:
        raise HTTPException(404, "User not found.")
    temporary = pysecrets.token_urlsafe(9)
    user.password_hash = accounts.hash_password(temporary)
    db.commit()
    accounts.destroy_user_sessions(db, user.id)
    return {"temporary_password": temporary}


# --- migration: owner-only backup, restore into an empty instance -----------------------


@app.get("/api/admin/backup")
def admin_backup(_: User = Depends(admin)):
    """Consistent copy of the SQLite database (owner only). Postgres deployments
    use the provider's own dump tools."""
    import sqlite3
    import tempfile
    from pathlib import Path as _Path

    if not settings.database_url.startswith("sqlite"):
        raise HTTPException(409, "Backup download is only available for SQLite databases.")
    with tempfile.TemporaryDirectory() as tmp:
        target = _Path(tmp) / "backup.db"
        raw = engine.raw_connection()
        try:
            dest = sqlite3.connect(str(target))
            try:
                raw.driver_connection.backup(dest)
            finally:
                dest.close()
        finally:
            raw.close()
        data = target.read_bytes()
    return RawResponse(
        data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": "attachment; filename=career-backup.sqlite3", "Content-Length": str(len(data))},
    )


@app.post("/api/admin/restore")
async def admin_restore(request: Request, file: UploadFile = File(...), db=Depends(db_session)):
    """Load a backup into an instance that has no accounts yet. Requires the
    setup code (APP_TOKEN) in the Authorization header, like the first sign-up."""
    bearer = request.headers.get("authorization", "").removeprefix("Bearer ")
    if not (settings.app_token and hmac.compare_digest(bearer, settings.app_token)):
        raise HTTPException(401, "Provide the setup code as a bearer token.")
    if not settings.database_url.startswith("sqlite"):
        raise HTTPException(409, "Restore is only available for SQLite databases.")
    if db.query(User).count():
        raise HTTPException(409, "This instance already has accounts. Restore only into an empty instance.")
    import sqlite3
    import tempfile
    from pathlib import Path as _Path

    data = await file.read(200_000_000)
    if not data.startswith(b"SQLite format 3\x00"):
        raise HTTPException(422, "That file is not a SQLite database.")
    with tempfile.TemporaryDirectory() as tmp:
        source_path = _Path(tmp) / "restore.db"
        source_path.write_bytes(data)
        source = sqlite3.connect(str(source_path))
        try:
            tables = {r[0] for r in source.execute("select name from sqlite_master where type='table'")}
            if not {"records", "users"} <= tables:
                raise HTTPException(422, "The backup does not contain Jobs Find AI tables.")
            db.close()
            engine.dispose()
            raw = engine.raw_connection()
            try:
                source.backup(raw.driver_connection)
            finally:
                raw.close()
        finally:
            source.close()
    engine.dispose()
    initialize()
    with Session() as fresh:
        return {"restored": True, "accounts": fresh.query(User).count(), "records": fresh.query(Record).count()}


# --- workspace state -------------------------------------------------------------------


@app.get("/api/state")
def state(user: User = Depends(auth), db=Depends(db_session)):
    alerts = [item(r) for r in rows(db, "alert")]
    limits = accounts.plan_limits(user.plan)
    return {
        "user": user.public(),
        "plan": {"id": user.plan, **limits, "packages_used": accounts.packages_this_month(db), "evaluations_used": accounts.evaluations_this_month(db), **billing.plan_status(user)},
        "app_name": settings.app_name,
        "profile": read(db, "profile", Profile().model_dump()),
        "preferences": {**Preferences().model_dump(), **read(db, "preferences", {})},
        "schedule": read(db, "schedule", {"enabled": False}),
        "scheduler": scheduler.status(),
        "jobs": [job_summary(r) for r in rows(db, "job")],
        "sources": [item(r) for r in rows(db, "source")],
        "applications": [item(r) for r in rows(db, "application")],
        "runs": sorted(
            [item(r) for r in rows(db, "run")],
            key=lambda r: r.get("created", ""),
            reverse=True,
        )[:10],
        "connections": availability(db),
        "alerts": alerts,
        "inbox_unread": sum(1 for a in alerts if a.get("channel") == "inapp" and a.get("status") == "unread"),
        "telegram": telegram.link_status(db),
        "source_kinds": KIND_LABELS,
        "suggested_sources": SUGGESTED_SOURCES,
    }


@app.get("/api/jobs/{id}", dependencies=[Depends(auth)])
def job_detail(id: str, db=Depends(db_session)):
    row = row_or_404(db, id, "job")
    return {**item(row), "expired": expired(row.data)}


@app.post("/api/profile/upload")
async def upload(file: UploadFile = File(...), user: User = Depends(auth), db=Depends(db_session)):
    ai_action(user, "CV extraction")
    data = await file.read(5_000_001)
    if len(data) > 5_000_000:
        raise HTTPException(413, "Maximum upload size is 5 MB.")
    try:
        text = await run_in_threadpool(extract_text, data, file.filename or "")
        profile = await run_in_threadpool(extract_profile, text)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except Exception:
        raise HTTPException(
            422,
            "Could not process the document. Check its format and AI configuration, or paste the text.",
        )
    put(db, "profile_source", "profile_source", {"text": text, "filename": file.filename})
    put(db, "profile", "profile", profile.model_dump())
    invalidate_matches(db)
    return profile


class TextImport(BaseModel):
    text: str = Field(min_length=40, max_length=100000)


@app.post("/api/profile/text")
def profile_text(body: TextImport, user: User = Depends(auth), db=Depends(db_session)):
    ai_action(user, "CV extraction")
    try:
        profile = extract_profile(body.text)
    except ValueError as e:
        raise HTTPException(422, str(e))
    put(db, "profile_source", "profile_source", {"text": body.text, "filename": "Pasted CV"})
    put(db, "profile", "profile", profile.model_dump())
    invalidate_matches(db)
    return profile


def invalidate_matches(db):
    for row in rows(db, "job"):
        if row.data.get("match") is not None:
            row.data = {**row.data, "match": None}
    db.commit()


def evidence_hash(profile):
    verified = sorted(
        (f.get("id", ""), f.get("text", ""))
        for f in profile.get("facts", [])
        if f.get("verified")
    )
    return hashlib.sha256(json.dumps(verified).encode()).hexdigest()


@app.put("/api/profile", dependencies=[Depends(auth)])
def save_profile(profile: Profile, db=Depends(db_session)):
    if len({f.id for f in profile.facts}) != len(profile.facts):
        raise HTTPException(422, "Evidence IDs must be unique.")
    previous = read(db, "profile", {})
    put(db, "profile", "profile", profile.model_dump())
    if evidence_hash(previous) != evidence_hash(profile.model_dump()):
        invalidate_matches(db)
    return profile


@app.put("/api/preferences", dependencies=[Depends(auth)])
def prefs(prefs: Preferences, db=Depends(db_session)):
    previous = {**Preferences().model_dump(), **read(db, "preferences", {})}
    put(db, "preferences", "preferences", prefs.model_dump())
    current = prefs.model_dump()
    if any(previous.get(k) != current.get(k) for k in MATCH_RELEVANT_PREFERENCES):
        invalidate_matches(db)
    return prefs


class Schedule(BaseModel):
    enabled: bool


@app.put("/api/schedule")
def schedule(body: Schedule, user: User = Depends(auth), db=Depends(db_session)):
    if body.enabled and not accounts.plan_limits(user.plan)["schedule"]:
        raise HTTPException(403, "Scheduled searches are not included in your plan.")
    return item(put(db, "schedule", "schedule", body.model_dump()))


@app.post("/api/sources")
def source(body: SourceInput, user: User = Depends(auth), db=Depends(db_session)):
    try:
        validate_source(body.kind, body.value)
    except ValueError as e:
        raise HTTPException(422, str(e))
    value = body.value.strip()
    key = f"source:{body.kind}:{value}"
    if not find(db, key) and len(rows(db, "source")) >= accounts.plan_limits(user.plan)["sources"]:
        raise HTTPException(403, "Your plan's source limit is reached. Remove a source or upgrade.")
    return item(put(db, "source", key, {**body.model_dump(), "value": value}))


@app.put("/api/sources/{id}", dependencies=[Depends(auth)])
def toggle_source(id: str, body: Schedule, db=Depends(db_session)):
    row = row_or_404(db, id, "source")
    return item(put(db, "source", row.key, {**row.data, "enabled": body.enabled}))


@app.delete("/api/sources/{id}", dependencies=[Depends(auth)])
def delete_source(id: str, db=Depends(db_session)):
    db.delete(row_or_404(db, id, "source"))
    db.commit()
    return {"ok": True}


@app.post("/api/sources/test")
async def test_source(body: SourceInput, user: User = Depends(auth)):
    """Read a source once with a small budget and report what came back."""
    if body.kind in ("page", "gmail", "imap"):
        ai_action(user, "source test")
    try:
        validate_source(body.kind, body.value)
        jobs, _ = await run_in_threadpool(
            collect, body.model_dump(), None, Context(page_budget=3, delay=0.5, sample=True)
        )
    except ValueError as e:
        raise HTTPException(422, str(e))
    except Exception as e:
        raise HTTPException(
            502,
            f"The source could not be read ({type(e).__name__}). Check the identifier or address and that the provider is reachable.",
        )
    full = [j for j in jobs if not j.get("partial")]
    return {
        "received": len(jobs),
        "sample": [
            {"title": j["title"], "company": j.get("company", ""), "location": j.get("location", ""), "url": j.get("url", "")}
            for j in full[:8]
        ],
    }


@app.post("/api/jobs", dependencies=[Depends(auth)])
def add_job(job: JobInput, db=Depends(db_session)):
    try:
        row, created = ingest(db, job.model_dump())
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {**item(row), "created_new": created}


class Decision(BaseModel):
    status: Literal["new", "saved", "skipped", "applied", "archived"]


@app.put("/api/jobs/{id}/decision", dependencies=[Depends(auth)])
def decide(id: str, body: Decision, db=Depends(db_session)):
    row = row_or_404(db, id, "job")
    return item(put(db, "job", row.key, {**row.data, "status": body.status}))


@app.post("/api/jobs/{id}/match")
def match(id: str, user: User = Depends(auth), db=Depends(db_session)):
    ai_action(user, "match evaluation")
    row = row_or_404(db, id, "job")
    if not any(f.get("verified") for f in read(db, "profile", {}).get("facts", [])):
        raise HTTPException(409, "Upload and verify your CV evidence first.")
    try:
        return item(evaluate(db, row))
    except ValueError as e:
        raise HTTPException(422, str(e))
    except Exception:
        raise HTTPException(502, "Matching failed. Check the AI connection and retry.")


@app.post("/api/jobs/{id}/prepare")
def prepare(id: str, tasks: BackgroundTasks, user: User = Depends(auth), db=Depends(db_session)):
    ai_action(user, "application preparation")
    job = row_or_404(db, id, "job")
    if not ai_available():
        raise HTTPException(409, "Add your OpenAI API key under Account before preparing documents.")
    if expired(job.data):
        raise HTTPException(409, "This job's deadline has passed.")
    if not any(f.get("verified") for f in read(db, "profile", {}).get("facts", [])):
        raise HTTPException(409, "Verify your CV evidence first.")
    old = read(db, "application:" + id)
    if old and old.get("status") in ("queued", "preparing", "review", "ready"):
        started = datetime.fromisoformat(old.get("approved_at", now()))
        if old["status"] in ("review", "ready") or started > datetime.now(timezone.utc) - timedelta(minutes=10):
            return old
    if not old and accounts.packages_this_month(db) >= accounts.plan_limits(user.plan)["packages_per_month"]:
        credits = int((user.settings or {}).get("credits") or 0)
        if credits <= 0:
            raise HTTPException(403, "Your plan's monthly application limit is reached. Upgrade or buy application packages under Account.")
        user.settings = {**(user.settings or {}), "credits": credits - 1}
        db.commit()
    row = put(
        db,
        "application",
        "application:" + id,
        {
            "job_id": id,
            "title": job.data["title"],
            "company": job.data["company"],
            "status": "queued",
            "approved_at": now(),
        },
    )
    put(db, "job", job.key, {**job.data, "status": "saved"})
    if settings.task_queue == "celery":
        from .tasks import prepare as queued_prepare

        try:
            queued_prepare.delay(id, user.id)
        except Exception:
            put(db, "application", row.key, {**row.data, "status": "failed", "error": "Worker queue unavailable. Restart Redis and the worker, then retry."})
            raise HTTPException(503, "Worker queue unavailable.")
    else:
        tasks.add_task(prepare_application, id, user.id)
    return item(row)


class PackageEdit(BaseModel):
    package: Package
    status: Literal["review", "ready"] = "review"


@app.put("/api/applications/{id}", dependencies=[Depends(auth)])
def edit_application(id: str, body: PackageEdit, db=Depends(db_session)):
    row = row_or_404(db, id, "application")
    for answer in body.package.answers:
        if answer.character_limit and len(answer.answer) > answer.character_limit:
            raise HTTPException(422, "A screening answer exceeds its character limit.")
    put(
        db,
        "application_version",
        "application_version:" + uuid4().hex,
        {"application_id": id, "saved_at": now(), "previous": row.data},
    )
    return item(
        put(
            db,
            "application",
            row.key,
            {**row.data, "package": body.package.model_dump(), "status": body.status, "reviewed_at": now()},
        )
    )


@app.get("/api/applications/{id}/versions", dependencies=[Depends(auth)])
def application_versions(id: str, db=Depends(db_session)):
    row_or_404(db, id, "application")
    return [item(r) for r in rows(db, "application_version") if r.data.get("application_id") == id]


@app.get("/api/applications/{id}/download", dependencies=[Depends(auth)])
def download(id: str, db=Depends(db_session)):
    row = row_or_404(db, id, "application")
    if not row.data.get("package"):
        raise HTTPException(409, "Documents are not ready yet.")
    content = package_zip(row.data["package"], row.data.get("profile_snapshot", {}).get("name", ""))
    return RawResponse(
        content,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=application_package.zip"},
    )


@app.post("/api/scan")
def scan(tasks: BackgroundTasks, user: User = Depends(auth), db=Depends(db_session)):
    for current in rows(db, "run"):
        if current.data.get("status") in ("queued", "running") and datetime.fromisoformat(
            current.data["created"]
        ) > datetime.now(timezone.utc) - timedelta(minutes=30):
            return item(current)
    row = put(db, "run", "run:" + uuid4().hex, {"status": "queued", "created": now(), "trigger": "manual"})
    if settings.task_queue == "celery":
        from .tasks import scan_existing

        try:
            scan_existing.delay(row.id, user.id)
        except Exception:
            put(db, "run", row.key, {**row.data, "status": "failed", "error": "Worker queue unavailable."})
            raise HTTPException(503, "Worker queue unavailable.")
    else:
        tasks.add_task(run_scan, row.id, user.id)
    return item(row)


class InboxRead(BaseModel):
    job_ids: list[str] = Field(default_factory=list)


@app.post("/api/inbox/read", dependencies=[Depends(auth)])
def inbox_read(body: InboxRead, db=Depends(db_session)):
    changed = 0
    for row in rows(db, "alert"):
        if row.data.get("channel") != "inapp" or row.data.get("status") != "unread":
            continue
        if body.job_ids and row.data.get("job_id") not in body.job_ids:
            continue
        put(db, "alert", row.key, {**row.data, "status": "read", "read_at": now()})
        changed += 1
    return {"read": changed}


@app.post("/api/alerts/{id}/resend", dependencies=[Depends(auth)])
async def resend_alert(id: str, db=Depends(db_session)):
    """Manual recovery for an alert whose delivery was unknown or failed."""
    row = row_or_404(db, id, "alert")
    if row.data.get("channel") == "inapp":
        raise HTTPException(422, "In-app alerts are not sent anywhere.")
    if row.data.get("status") not in ("delivery_unknown", "failed"):
        raise HTTPException(422, "Only alerts with unknown or failed delivery can be resent.")
    job = get_row(db, row.data.get("job_id", ""), "job")
    if not job or not job.data.get("match"):
        raise HTTPException(409, "The job or its evaluation no longer exists.")
    from .notifications import send_alert, telegram_chat

    try:
        await run_in_threadpool(send_alert, row.data["channel"], job.data, job.data["match"], job.id, telegram_chat(db))
        status = "accepted"
    except Exception:
        status = "delivery_unknown"
    put(db, "alert", row.key, {**row.data, "status": status, "resent_at": now(), "resends": (row.data.get("resends") or 0) + 1})
    return {"status": status}


@app.post("/api/notify/test/{channel}", dependencies=[Depends(auth)])
async def notify_test(channel: Literal["email", "telegram", "whatsapp"], db=Depends(db_session)):
    try:
        return await run_in_threadpool(test_alert, db, channel)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except Exception as e:
        raise HTTPException(502, f"The provider rejected the test message ({type(e).__name__}). Check the server credentials.")


@app.post("/api/telegram/link", dependencies=[Depends(auth)])
async def telegram_link(db=Depends(db_session)):
    if not settings.telegram_bot_token:
        raise HTTPException(409, "Telegram is not configured on this server.")
    code = telegram.create_link_code(db)
    username = await run_in_threadpool(telegram.bot_username)
    return {"code": code, "bot_username": username, "expires_minutes": 15, **telegram.link_status(db)}


@app.delete("/api/telegram/link", dependencies=[Depends(auth)])
def telegram_unlink(db=Depends(db_session)):
    for key in ("telegram", "telegram_link"):
        row = find(db, key)
        if row:
            db.delete(row)
    db.commit()
    return telegram.link_status(db)


@app.post("/api/telegram/webhook")
async def telegram_webhook(request: Request, db=Depends(db_session)):
    """Optional webhook for HTTPS deployments. Local installs use long polling."""
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not settings.telegram_webhook_secret or not hmac.compare_digest(secret, settings.telegram_webhook_secret):
        raise HTTPException(401, "Invalid webhook.")
    data = await request.json()
    if data.get("message"):
        await run_in_threadpool(telegram.handle_message, db, data["message"])
        return {"ok": True}
    callback = data.get("callback_query")
    if not callback:
        return {"ok": True}
    chat = str(callback.get("message", {}).get("chat", {}).get("id", ""))
    sender = str(callback.get("from", {}).get("id", ""))
    if not chat or chat != sender or not telegram.user_for_chat(db, chat):
        raise HTTPException(403, "Wrong Telegram user.")
    await run_in_threadpool(telegram.handle_callback, db, callback)
    return {"ok": True}


# The app lives under /app; the public landing page (and legal pages) at /.
if settings.dashboard_dir.is_dir():
    app.mount("/app", StaticFiles(directory=settings.dashboard_dir, html=True), name="dashboard")
if settings.landing_dir.is_dir():
    app.mount("/", StaticFiles(directory=settings.landing_dir, html=True), name="landing")
