"""Billing: paid plans and application-package credits.

Three ways to pay, chosen by what is configured:
- Chapa (Ethiopia, ETB): hosted checkout, verified server-side, webhook as backup.
- Lemon Squeezy (cards worldwide, USD): hosted checkout links from the dashboard, webhook applies the purchase.
- Manual: when neither gateway is set, the member sends a payment request; the owner
  receives an email, collects the money (Telebirr, bank transfer) and activates the
  purchase in the Cohort tab.

A purchase is a system record (kind "payment"). Applying it is idempotent."""

import hashlib
import hmac
import json
import logging
import secrets
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode
import httpx
from .config import settings
from .db import SYSTEM, User, put, read, rows, now
from . import telemetry

log = logging.getLogger(__name__)
PLAN_DAYS = 31

PRODUCTS = {
    "pro": {"label": "Pro, one month", "plan": "pro", "days": PLAN_DAYS},
    "pro_plus": {"label": "Pro Plus, one month", "plan": "pro_plus", "days": PLAN_DAYS},
    "package": {"label": "1 application package", "credits": 1},
    "package_5": {"label": "5 application packages", "credits": 5},
}


def price(product, currency):
    etb = currency == "ETB"
    if product == "pro":
        return settings.price_pro_etb if etb else settings.price_pro_usd
    if product == "pro_plus":
        return settings.price_pro_plus_etb if etb else settings.price_pro_plus_usd
    if product == "package":
        return settings.price_package_etb if etb else settings.price_package_usd
    if product == "package_5":
        return (settings.price_package_etb if etb else settings.price_package_usd) * 4
    raise ValueError("Unknown product.")


def gateways():
    return {
        "chapa": bool(settings.chapa_secret_key),
        "lemon": bool(settings.lemon_checkout_pro or settings.lemon_checkout_pro_plus or settings.lemon_checkout_package),
        "manual": True,
    }


def catalog():
    """Public prices for the landing page and the Account tab."""
    return {
        "currencies": ["ETB", "USD"],
        "plans": {
            "free": {"etb": 0, "usd": 0},
            "pro": {"etb": settings.price_pro_etb, "usd": settings.price_pro_usd},
            "pro_plus": {"etb": settings.price_pro_plus_etb, "usd": settings.price_pro_plus_usd},
        },
        "package": {"etb": settings.price_package_etb, "usd": settings.price_package_usd},
        "package_5": {"etb": settings.price_package_etb * 4, "usd": settings.price_package_usd * 4},
        "featured_listing": {"etb": settings.featured_listing_etb, "usd": settings.featured_listing_usd, "days": 14},
        "institution_seat": {"etb": settings.institution_seat_etb, "usd": settings.institution_seat_usd, "minimum_seats": 25},
        "gateways": gateways(),
        "billing_contact": settings.billing_contact or settings.email_from,
    }


# --- purchases -------------------------------------------------------------------


def _payment_key(ref):
    return "payment:" + ref


def new_payment(db, user, product, currency, provider, extra=None):
    ref = "jfa-" + secrets.token_hex(8)
    data = {
        "ref": ref,
        "user_id": user.id,
        "email": user.email,
        "product": product,
        "amount": price(product, currency),
        "currency": currency,
        "provider": provider,
        "status": "pending",
        "created": now(),
        **(extra or {}),
    }
    put(db, "payment", _payment_key(ref), data, user_id=SYSTEM)
    return data


def payments(db, user_id=None):
    out = [r.data for r in rows(db, "payment", user_id=SYSTEM)]
    if user_id:
        out = [p for p in out if p.get("user_id") == user_id]
    return sorted(out, key=lambda p: p.get("created", ""), reverse=True)


def apply_purchase(db, ref, provider_ref=None):
    """Grant what was bought. Safe to call twice: a paid record is not applied again."""
    data = read(db, _payment_key(ref), user_id=SYSTEM)
    if not data:
        raise ValueError("Unknown payment reference.")
    if data.get("status") == "paid":
        return data
    user = db.get(User, data["user_id"])
    if not user:
        raise ValueError("The paying account no longer exists.")
    product = PRODUCTS[data["product"]]
    user_settings = dict(user.settings or {})
    if "plan" in product:
        current_until = _parse(user_settings.get("plan_until"))
        base = current_until if current_until and current_until > datetime.now(timezone.utc) and user.plan == product["plan"] else datetime.now(timezone.utc)
        user_settings["plan_until"] = (base + timedelta(days=product["days"])).isoformat()
        user_settings["plan_before_purchase"] = user_settings.get("plan_before_purchase") or user.plan
        user.plan = product["plan"]
    else:
        user_settings["credits"] = int(user_settings.get("credits") or 0) + product["credits"]
    user.settings = user_settings
    db.commit()
    data = {**data, "status": "paid", "paid_at": now(), "provider_ref": provider_ref}
    put(db, "payment", _payment_key(ref), data, user_id=SYSTEM)
    telemetry.capture("server_purchase", {"product": data["product"], "currency": data["currency"], "amount": data["amount"], "provider": data["provider"]}, distinct_id=user.id)
    return data


def _parse(stamp):
    try:
        return datetime.fromisoformat(stamp) if stamp else None
    except (TypeError, ValueError):
        return None


def expire_plans(db):
    """Paid plans that ran out return to what the member had before (free, beta or sponsored)."""
    changed = 0
    for user in db.query(User).all():
        s = user.settings or {}
        until = _parse(s.get("plan_until"))
        if user.plan in ("pro", "pro_plus") and until and until < datetime.now(timezone.utc) and user.role != "admin":
            before = s.get("plan_before_purchase") or ("sponsored" if s.get("sponsored") else "beta")
            user.plan = "sponsored" if s.get("sponsored") else (before if before in ("free", "beta") else "beta")
            user.settings = {k: v for k, v in s.items() if k not in ("plan_until", "plan_before_purchase")}
            changed += 1
    if changed:
        db.commit()
    return changed


def plan_status(user):
    s = user.settings or {}
    return {"plan_until": s.get("plan_until"), "credits": int(s.get("credits") or 0)}


# --- checkout --------------------------------------------------------------------


def start_checkout(db, user, product, currency):
    if product not in PRODUCTS:
        raise ValueError("Unknown product.")
    currency = (currency or "ETB").upper()
    if currency not in ("ETB", "USD"):
        raise ValueError("Currency must be ETB or USD.")
    if currency == "ETB" and settings.chapa_secret_key:
        return chapa_checkout(db, user, product)
    if currency == "USD":
        link = {"pro": settings.lemon_checkout_pro, "pro_plus": settings.lemon_checkout_pro_plus, "package": settings.lemon_checkout_package, "package_5": settings.lemon_checkout_package}.get(product)
        if link:
            payment = new_payment(db, user, product, "USD", "lemonsqueezy")
            sep = "&" if "?" in link else "?"
            url = link + sep + urlencode({"checkout[custom][ref]": payment["ref"], "checkout[custom][user_id]": user.id, "checkout[email]": user.email})
            return {"mode": "redirect", "provider": "lemonsqueezy", "url": url, "ref": payment["ref"]}
    return manual_request(db, user, product, currency)


def chapa_checkout(db, user, product):
    payment = new_payment(db, user, product, "ETB", "chapa")
    base = settings.public_url.rstrip("/")
    body = {
        "amount": str(payment["amount"]),
        "currency": "ETB",
        "email": user.email,
        "first_name": (user.name or "Member").split()[0][:50],
        "last_name": " ".join((user.name or "").split()[1:])[:50] or "-",
        "tx_ref": payment["ref"],
        "callback_url": base + "/api/billing/webhook/chapa",
        "return_url": base + "/api/billing/return?ref=" + payment["ref"],
        "customization": {"title": settings.app_name[:16], "description": PRODUCTS[product]["label"][:50]},
    }
    r = httpx.post("https://api.chapa.co/v1/transaction/initialize", json=body, headers={"Authorization": "Bearer " + settings.chapa_secret_key}, timeout=30)
    data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if r.status_code >= 300 or data.get("status") != "success":
        log.warning("Chapa initialize failed: %s %s", r.status_code, str(data.get("message"))[:200])
        raise ValueError("The payment provider could not start the checkout. Try again or contact support.")
    return {"mode": "redirect", "provider": "chapa", "url": data["data"]["checkout_url"], "ref": payment["ref"]}


def chapa_verify(db, ref):
    """Ask Chapa whether a transaction succeeded; apply it if so. Never trusts the browser."""
    r = httpx.get("https://api.chapa.co/v1/transaction/verify/" + ref, headers={"Authorization": "Bearer " + settings.chapa_secret_key}, timeout=30)
    data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    tx = data.get("data") or {}
    payment = read(db, _payment_key(ref), user_id=SYSTEM)
    if not payment:
        raise ValueError("Unknown payment reference.")
    ok = data.get("status") == "success" and tx.get("status") == "success" and str(tx.get("currency", "")).upper() == "ETB" and float(tx.get("amount") or 0) >= float(payment["amount"])
    if ok:
        return apply_purchase(db, ref, provider_ref=tx.get("reference"))
    return payment


def chapa_webhook(db, raw_body: bytes, signature: str):
    if not settings.chapa_webhook_secret:
        raise ValueError("Webhook secret not configured.")
    expected = hmac.new(settings.chapa_webhook_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    if not signature or not hmac.compare_digest(expected, signature):
        raise PermissionError("Bad signature.")
    payload = json.loads(raw_body or b"{}")
    ref = payload.get("tx_ref") or payload.get("trx_ref") or (payload.get("data") or {}).get("tx_ref")
    if not ref:
        raise ValueError("No transaction reference.")
    return chapa_verify(db, ref)


def lemon_webhook(db, raw_body: bytes, signature: str):
    if not settings.lemon_webhook_secret:
        raise ValueError("Webhook secret not configured.")
    expected = hmac.new(settings.lemon_webhook_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    if not signature or not hmac.compare_digest(expected, signature):
        raise PermissionError("Bad signature.")
    payload = json.loads(raw_body or b"{}")
    event = (payload.get("meta") or {}).get("event_name", "")
    custom = (payload.get("meta") or {}).get("custom_data") or {}
    attributes = (payload.get("data") or {}).get("attributes") or {}
    if event not in ("order_created", "subscription_payment_success"):
        return {"ignored": event}
    if event == "order_created" and attributes.get("status") not in (None, "paid"):
        return {"ignored": "unpaid order"}
    ref = custom.get("ref")
    if not ref:
        raise ValueError("No payment reference in custom data.")
    return apply_purchase(db, ref, provider_ref=str((payload.get("data") or {}).get("id")))


def manual_request(db, user, product, currency):
    from .notifications import email_send

    payment = new_payment(db, user, product, currency, "manual", {"status": "requested"})
    contact = settings.billing_contact or settings.email_from or "the owner"
    owner_email = settings.email_to or settings.email_from
    if settings.smtp_host and settings.email_from and owner_email:
        try:
            email_send(
                f"{settings.app_name}: payment request from {user.email}",
                f"{user.name or user.email} ({user.email}) wants to buy {PRODUCTS[product]['label']} for {payment['amount']} {currency}.\n\nReference: {payment['ref']}\n\nOnce you have received the money, open the Cohort tab and mark the request as paid. That activates it immediately.",
                to=owner_email,
            )
        except Exception as e:
            log.warning("Payment request email failed: %s", type(e).__name__)
    return {
        "mode": "manual",
        "ref": payment["ref"],
        "amount": payment["amount"],
        "currency": currency,
        "instructions": f"Send {payment['amount']} {currency} to {contact} with the reference {payment['ref']}, or reply to the confirmation email. Your purchase is activated as soon as the payment is confirmed, usually the same day.",
    }
