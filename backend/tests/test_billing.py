"""Billing: catalog, manual requests, Chapa and Lemon Squeezy flows, plan expiry, package credits, server key for paid plans."""

import hashlib
import hmac
import json
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from career.config import settings
from career.db import Session, User
from career.main import app
from career import billing, ai
from tests.conftest import signup_member
from tests.test_workflow import JOB, verified_profile, package


def member_user(email="member@example.org"):
    with Session() as db:
        return db.query(User).filter_by(email=email).one()


def test_catalog_is_public_and_manual_request_emails_owner(client, monkeypatch):
    sent = []
    monkeypatch.setattr("career.notifications.email_send", lambda subject, text, to=None: sent.append((subject, text, to)))
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.org")
    monkeypatch.setattr(settings, "email_from", "owner@example.org")
    monkeypatch.setattr(settings, "billing_contact", "Telebirr 0911 000 000")
    c = TestClient(app).get("/api/public/pricing").json()
    assert c["plans"]["pro"]["etb"] == settings.price_pro_etb and c["gateways"] == {"chapa": False, "lemon": False, "manual": True}
    member = signup_member(client)
    r = member.post("/api/billing/checkout", json={"product": "pro", "currency": "ETB"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["mode"] == "manual" and out["amount"] == settings.price_pro_etb and "Telebirr 0911 000 000" in out["instructions"] and out["ref"].startswith("jfa-")
    assert sent and "payment request" in sent[0][0] and out["ref"] in sent[0][1] and sent[0][2] == "owner@example.org"
    # Owner sees the request and activates it; member gets Pro for 31 days and the server key.
    overview = client.get("/api/admin/overview").json()
    assert any(p["ref"] == out["ref"] and p["status"] == "requested" for p in overview["payments"])
    paid = client.post(f"/api/admin/payments/{out['ref']}/paid").json()
    assert paid["status"] == "paid"
    state = member.get("/api/state").json()
    assert state["plan"]["id"] == "pro" and state["plan"]["plan_until"] and state["plan"]["evaluations_per_month"] == 600
    until = datetime.fromisoformat(state["plan"]["plan_until"])
    assert 29 <= (until - datetime.now(timezone.utc)).days <= 31
    # Applying twice does not extend again.
    client.post(f"/api/admin/payments/{out['ref']}/paid")
    assert member.get("/api/state").json()["plan"]["plan_until"] == state["plan"]["plan_until"]
    assert member.get("/api/billing").json()["payments"][0]["status"] == "paid"
    # A second month stacks on the current one.
    ref2 = member.post("/api/billing/checkout", json={"product": "pro", "currency": "USD"}).json()["ref"]
    client.post(f"/api/admin/payments/{ref2}/paid")
    until2 = datetime.fromisoformat(member.get("/api/state").json()["plan"]["plan_until"])
    assert 59 <= (until2 - datetime.now(timezone.utc)).days <= 62
    # Paid members without a key use the server key.
    monkeypatch.setattr(settings, "openai_api_key", "server-key")
    from career.db import user_scope, user_snapshot

    with user_scope(user_snapshot(member_user())):
        assert ai.api_key() == "server-key" and ai.using_server_key()


def test_chapa_checkout_verify_and_webhook(client, monkeypatch):
    monkeypatch.setattr(settings, "chapa_secret_key", "CHASECK_TEST-abc")
    monkeypatch.setattr(settings, "chapa_webhook_secret", "hook-secret")
    calls = []

    class R:
        def __init__(self, payload, status=200):
            self._p, self.status_code, self.headers = payload, status, {"content-type": "application/json"}

        def json(self):
            return self._p

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append(("post", url, json))
        assert headers["Authorization"] == "Bearer CHASECK_TEST-abc" and json["currency"] == "ETB" and json["callback_url"].endswith("/api/billing/webhook/chapa")
        return R({"status": "success", "data": {"checkout_url": "https://checkout.chapa.co/x/" + json["tx_ref"]}})

    verified = {}

    def fake_get(url, headers=None, timeout=None):
        ref = url.rsplit("/", 1)[1]
        calls.append(("get", url, None))
        return R({"status": "success", "data": {"status": verified.get(ref, "pending"), "currency": "ETB", "amount": str(settings.price_pro_plus_etb), "reference": "CHAPA-1"}})

    monkeypatch.setattr(billing.httpx, "post", fake_post)
    monkeypatch.setattr(billing.httpx, "get", fake_get)
    member = signup_member(client)
    resp = member.post("/api/billing/checkout", json={"product": "pro_plus", "currency": "ETB"})
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["mode"] == "redirect" and out["provider"] == "chapa" and out["url"].endswith(out["ref"])
    # Member returns before paying: nothing granted.
    r = TestClient(app).get("/api/billing/return?ref=" + out["ref"], follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("/app/?payment=pending")
    assert member.get("/api/state").json()["plan"]["id"] != "pro_plus"
    # Webhook with a bad signature is rejected; a good one verifies with Chapa and applies.
    verified[out["ref"]] = "success"
    body = json.dumps({"tx_ref": out["ref"], "status": "success"}).encode()
    assert TestClient(app).post("/api/billing/webhook/chapa", content=body, headers={"x-chapa-signature": "nope"}).status_code == 401
    sig = hmac.new(b"hook-secret", body, hashlib.sha256).hexdigest()
    assert TestClient(app).post("/api/billing/webhook/chapa", content=body, headers={"x-chapa-signature": sig}).status_code == 200
    state = member.get("/api/state").json()
    assert state["plan"]["id"] == "pro_plus" and state["plan"]["packages_per_month"] == 30
    # The return URL now reports paid, and the purchase is not applied twice.
    r = TestClient(app).get("/api/billing/return?ref=" + out["ref"], follow_redirects=False)
    assert r.headers["location"].endswith("/app/?payment=paid")


def lemon_event(ref, event="order_created", **attributes):
    payload = json.dumps({"meta": {"event_name": event, "custom_data": {"ref": ref}}, "data": {"id": "123", "attributes": {"status": "paid", **attributes}}}).encode()
    sig = hmac.new(b"lemon-secret", payload, hashlib.sha256).hexdigest()
    return TestClient(app).post("/api/billing/webhook/lemonsqueezy", content=payload, headers={"x-signature": sig})


def cents(usd):
    return int(round(usd * 100))


def test_lemon_checkout_link_and_webhook(client, monkeypatch):
    monkeypatch.setattr(settings, "lemon_checkout_package_5", "https://store.lemonsqueezy.com/checkout/buy/five")
    monkeypatch.setattr(settings, "lemon_webhook_secret", "lemon-secret")
    member = signup_member(client)
    out = member.post("/api/billing/checkout", json={"product": "package_5", "currency": "USD"}).json()
    assert out["mode"] == "redirect" and out["provider"] == "lemonsqueezy" and out["url"].startswith("https://store.lemonsqueezy.com/checkout/buy/five?")
    assert "checkout%5Bcustom%5D%5Bref%5D=" + out["ref"] in out["url"]
    payload = json.dumps({"meta": {"event_name": "order_created", "custom_data": {"ref": out["ref"]}}, "data": {"id": "123", "attributes": {"status": "paid"}}}).encode()
    assert TestClient(app).post("/api/billing/webhook/lemonsqueezy", content=payload, headers={"x-signature": "bad"}).status_code == 401
    assert lemon_event(out["ref"], currency="USD", total=cents(settings.price_package_usd * 4)).status_code == 200
    assert member.get("/api/state").json()["plan"]["credits"] == 5


def test_lemon_order_that_does_not_pay_for_the_checkout_is_held(client, monkeypatch):
    sent = []
    monkeypatch.setattr("career.notifications.email_send", lambda subject, text, to=None: sent.append(subject))
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.org")
    monkeypatch.setattr(settings, "email_from", "owner@example.org")
    monkeypatch.setattr(settings, "lemon_checkout_package", "https://store.lemonsqueezy.com/checkout/buy/one")
    monkeypatch.setattr(settings, "lemon_checkout_pro", "https://store.lemonsqueezy.com/checkout/buy/pro")
    monkeypatch.setattr(settings, "lemon_webhook_secret", "lemon-secret")
    member = signup_member(client)
    # Five packages have no Lemon link of their own: they become a manual request, not the one-package link.
    assert member.post("/api/billing/checkout", json={"product": "package_5", "currency": "USD"}).json()["mode"] == "manual"

    pro = member.post("/api/billing/checkout", json={"product": "pro", "currency": "USD"}).json()["ref"]
    # The Pro reference arrives on a cheaper order (the one-package product): held, nothing granted.
    r = lemon_event(pro, currency="USD", total=cents(settings.price_package_usd)).json()
    assert r == {"ok": True}
    payments = {p["ref"]: p for p in client.get("/api/admin/overview").json()["payments"]}
    assert payments[pro]["status"] == "held" and "expected" in payments[pro]["held_reason"]
    assert member.get("/api/state").json()["user"]["plan"] != "pro" and any("held for review" in s for s in sent)
    # Wrong currency is held too; a manual or Chapa reference is never applied by Lemon.
    other = member.post("/api/billing/checkout", json={"product": "pro", "currency": "USD"}).json()["ref"]
    lemon_event(other, currency="EUR", total=cents(settings.price_pro_usd * 2))
    manual = member.post("/api/billing/checkout", json={"product": "pro", "currency": "ETB"}).json()["ref"]
    lemon_event(manual, currency="USD", total=cents(settings.price_pro_usd))
    payments = {p["ref"]: p for p in client.get("/api/admin/overview").json()["payments"]}
    assert payments[other]["status"] == "held" and "EUR" in payments[other]["held_reason"]
    assert payments[manual]["status"] == "held" and "manual" in payments[manual]["held_reason"]
    business = client.get("/api/admin/business").json()
    assert business["all_time"]["count"] == 0 and len(business["held"]) == 3
    # The owner can still accept a held payment after checking the order.
    client.post(f"/api/admin/payments/{pro}/paid")
    assert member.get("/api/state").json()["user"]["plan"] == "pro"


def test_lemon_refunds_and_test_orders_are_not_revenue(client, monkeypatch):
    monkeypatch.setattr(settings, "lemon_checkout_package", "https://store.lemonsqueezy.com/checkout/buy/one")
    monkeypatch.setattr(settings, "lemon_webhook_secret", "lemon-secret")
    member = signup_member(client)
    paid = member.post("/api/billing/checkout", json={"product": "package", "currency": "USD"}).json()["ref"]
    trial = member.post("/api/billing/checkout", json={"product": "package", "currency": "USD"}).json()["ref"]
    lemon_event(paid, currency="USD", total=cents(settings.price_package_usd))
    lemon_event(trial, currency="USD", total=cents(settings.price_package_usd), test_mode=True)
    assert member.get("/api/state").json()["plan"]["credits"] == 2
    assert client.get("/api/admin/business").json()["all_time"] == {"ETB": 0, "USD": settings.price_package_usd, "count": 1}

    lemon_event(paid, event="order_refunded", status="refunded", currency="USD", refunded_amount=cents(settings.price_package_usd))
    business = client.get("/api/admin/business").json()
    assert business["all_time"]["count"] == 0 and business["refunds"] == {"count": 1, "ETB": 0, "USD": settings.price_package_usd}
    # A repeated order event does not re-apply a refunded payment.
    lemon_event(paid, currency="USD", total=cents(settings.price_package_usd))
    assert member.get("/api/state").json()["plan"]["credits"] == 2


def test_credits_extend_the_package_cap_and_plans_expire(client, monkeypatch):
    member = signup_member(client)
    verified_profile(member)
    monkeypatch.setattr(settings, "openai_api_key", "server-key")
    monkeypatch.setattr("career.service.write_package", lambda *a: package())
    with Session() as db:
        u = db.query(User).filter_by(email="member@example.org").one()
        u.plan = "free"
        u.settings = {"credits": 1}
        db.commit()
    monkeypatch.setattr("career.main.ai_available", lambda: True)
    j1 = member.post("/api/jobs", json=JOB).json()
    j2 = member.post("/api/jobs", json={**JOB, "url": "https://example.org/jobs/2", "title": "Second role"}).json()
    j3 = member.post("/api/jobs", json={**JOB, "url": "https://example.org/jobs/3", "title": "Third role"}).json()
    assert member.post(f"/api/jobs/{j1['id']}/prepare").status_code == 200  # free plan: 1 a month
    assert member.post(f"/api/jobs/{j2['id']}/prepare").status_code == 200  # the purchased credit
    assert member.get("/api/state").json()["plan"]["credits"] == 0
    r = member.post(f"/api/jobs/{j3['id']}/prepare")
    assert r.status_code == 403 and "buy application packages" in r.json()["detail"]
    # Expiry returns a lapsed Pro member to what they had before.
    with Session() as db:
        u = db.query(User).filter_by(email="member@example.org").one()
        u.plan = "pro"
        u.settings = {"plan_until": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(), "plan_before_purchase": "free"}
        db.commit()
        assert billing.expire_plans(db) == 1
        u = db.query(User).filter_by(email="member@example.org").one()
        assert u.plan == "free" and "plan_until" not in u.settings
