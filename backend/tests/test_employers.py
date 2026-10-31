"""Employer self-service: emailed sign-in link, payment after approval, statistics."""

import re
from fastapi.testclient import TestClient
from career.config import settings
from career.db import Record, Session, SYSTEM
from career.main import app
from career import public_jobs, employers
from tests.conftest import signup_member, CSRF
from tests.test_growth import POST
from tests.test_workflow import JOB

BROWSER = {"user-agent": "Mozilla/5.0 (Windows NT 10.0) Firefox/130.0"}


def mailbox(monkeypatch):
    sent = []
    monkeypatch.setattr("career.notifications.email_send", lambda subject, text, to=None: sent.append({"subject": subject, "text": text, "to": to}))
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.org")
    monkeypatch.setattr(settings, "email_from", "owner@example.org")
    return sent


def link_in(mail):
    return re.search(r"/employers/login\?token=(\S+)", mail["text"]).group(1)


def sign_in(token):
    employer = TestClient(app, headers=BROWSER)
    assert "Open my listings" in employer.get("/employers/login", params={"token": token}).text
    r = employer.post("/employers/login", data={"token": token}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/employers/dashboard"
    return employer


def submit(sent, **fields):
    anon = TestClient(app)
    r = anon.post("/api/employers/post", json={**POST, **fields}, headers=CSRF)
    assert r.status_code == 200
    return r.json()["id"]


def test_employer_signs_in_by_link_pays_after_approval_and_sees_statistics(client, monkeypatch):
    public_jobs.reset_cache()
    sent = mailbox(monkeypatch)
    post_id = submit(sent, title=JOB["title"], description=JOB["description"])
    # The owner is told; the employer gets a confirmation with a sign-in link.
    receipt = next(m for m in sent if m["to"] == "hr@example.org")
    assert "we received your vacancy" in receipt["subject"]
    employer = sign_in(link_in(receipt))
    page = employer.get("/employers/dashboard").text
    assert JOB["title"] in page and "Waiting for review" in page and "/checkout" not in page
    # A link works once.
    again = TestClient(app).post("/employers/login", data={"token": link_in(receipt)}, follow_redirects=False)
    assert again.status_code == 400 and "expired or was already used" in again.text

    # Approval emails a payment link; the listing is not public until paid.
    sent.clear()
    client.put(f"/api/admin/employer-posts/{post_id}", json={"status": "approved"})
    assert [m["to"] for m in sent] == ["hr@example.org"] and "approved" in sent[0]["subject"]
    assert all(j["title"] != JOB["title"] for j in TestClient(app).get("/api/public/jobs").json()["latest"])
    page = employer.get("/employers/dashboard").text
    assert "Approved. Pay" in page and "2,500 ETB" in page

    # No gateway configured: a manual request the owner confirms in the Cohort tab.
    r = employer.post(f"/employers/listings/{post_id}/checkout", data={"currency": "ETB"})
    assert r.status_code == 200 and "Payment instructions" in r.text
    payment = next(p for p in client.get("/api/admin/overview").json()["payments"] if p.get("post_id") == post_id)
    assert payment["product"] == "featured_listing" and payment["status"] == "requested" and payment["amount"] == settings.featured_listing_etb
    client.post(f"/api/admin/payments/{payment['ref']}/paid")
    assert "Live until" in employer.get("/employers/dashboard").text
    listed = TestClient(app).get("/api/public/jobs").json()["latest"][0]
    assert listed["title"] == JOB["title"] and listed["featured"]

    # Views of the job page and Apply clicks are counted; crawlers are not.
    visitor = TestClient(app, headers=BROWSER)
    page = visitor.get("/job/" + listed["slug"]).text
    assert f"/go/{post_id}" in page
    TestClient(app, headers={"user-agent": "Googlebot/2.1"}).get("/job/" + listed["slug"])
    r = visitor.get(f"/go/{post_id}", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == POST["url"]

    # Members whose keywords keep it get it in their search; each member counts once.
    member = signup_member(client)
    member.post("/api/scan")
    member.post("/api/scan")
    jobs = [j for j in member.get("/api/state").json()["jobs"] if j.get("featured_post") == post_id]
    assert len(jobs) == 1 and jobs[0]["source"] == "Featured employer"

    stats = next(p for p in client.get("/api/admin/overview").json()["employer_posts"] if p["id"] == post_id)
    assert stats["state"] == "live" and stats["stats"] == {"views": 1, "apply_clicks": 1, "matches": 1, "views_7d": 1, "apply_clicks_7d": 1}
    page = employer.get("/employers/dashboard").text
    assert "members whose search matched it" in page and "member@example.org" not in page

    # Paying again extends the period from its end, not from today.
    until = stats["featured_until"]
    extended = client.post(f"/api/admin/employer-posts/{post_id}/activate").json()["featured_until"]
    assert extended > until


def test_employer_sees_only_their_own_listings(client, monkeypatch):
    sent = mailbox(monkeypatch)
    mine = submit(sent)
    theirs = submit(sent, contact_email="other@example.org", title="Rangeland Ecologist")
    client.put(f"/api/admin/employer-posts/{theirs}", json={"status": "approved"})
    employer = sign_in(link_in(next(m for m in sent if m["to"] == "hr@example.org")))
    page = employer.get("/employers/dashboard").text
    assert POST["title"] in page and "Rangeland Ecologist" not in page
    assert employer.post(f"/employers/listings/{theirs}/checkout", data={"currency": "ETB"}).status_code == 404
    # A listing under review cannot be paid for yet.
    assert employer.post(f"/employers/listings/{mine}/checkout", data={"currency": "USD"}).status_code == 422
    # Without a session the dashboard sends people to sign in.
    assert TestClient(app).get("/employers/dashboard", follow_redirects=False).headers["location"] == "/employers"
    # Signing out ends the session.
    employer.post("/employers/logout")
    assert employer.get("/employers/dashboard", follow_redirects=False).status_code == 303


def test_sign_in_form_does_not_reveal_who_has_listings(client, monkeypatch):
    sent = mailbox(monkeypatch)
    submit(sent)
    sent.clear()
    anon = TestClient(app, headers=BROWSER)
    unknown = anon.post("/employers/link", data={"email": "nobody@example.org"}).text
    known = anon.post("/employers/link", data={"email": "HR@example.org"}).text
    assert "If that address has a vacancy with us" in unknown and "If that address has a vacancy with us" in known
    assert [m["to"] for m in sent] == ["hr@example.org"]
    # Forms posted from another site are refused.
    assert anon.post("/employers/link", data={"email": "hr@example.org"}, headers={"origin": "https://evil.example"}).status_code == 403
    # Sign-in records are stored hashed, never as the token itself.
    token = link_in(sent[0])
    with Session() as db:
        keys = [r.key for r in db.query(Record).filter_by(user_id=SYSTEM, kind="employer_token").all()]
    assert keys and all(token not in k for k in keys)


def test_featured_listing_pays_through_chapa_and_returns_to_the_employer(client, monkeypatch):
    sent = mailbox(monkeypatch)
    post_id = submit(sent)
    client.put(f"/api/admin/employer-posts/{post_id}", json={"status": "approved"})
    employer = sign_in(link_in(sent[-1]))
    monkeypatch.setattr(settings, "chapa_secret_key", "CHASECK-test")
    started = {}

    class Reply:
        status_code = 200
        headers = {"content-type": "application/json"}

        def __init__(self, data):
            self.data = data

        def json(self):
            return self.data

    def post(url, json=None, headers=None, timeout=None):
        started.update(json)
        return Reply({"status": "success", "data": {"checkout_url": "https://checkout.chapa.co/pay/abc"}})

    def get(url, headers=None, timeout=None):
        return Reply({"status": "success", "data": {"status": "success", "currency": "ETB", "amount": settings.featured_listing_etb, "reference": "CH-1"}})

    monkeypatch.setattr("career.billing.httpx.post", post)
    monkeypatch.setattr("career.billing.httpx.get", get)
    r = employer.post(f"/employers/listings/{post_id}/checkout", data={"currency": "ETB"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "https://checkout.chapa.co/pay/abc"
    assert started["email"] == "hr@example.org" and started["amount"] == str(settings.featured_listing_etb)
    back = TestClient(app).get("/api/billing/return", params={"ref": started["tx_ref"]}, follow_redirects=False)
    assert back.headers["location"].endswith("/employers/dashboard?payment=paid")
    with Session() as db:
        assert employers.state(next(r.data for r in db.query(Record).filter_by(user_id=SYSTEM, key="employer_post:" + post_id))) == "live"
