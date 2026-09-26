"""Growth: employer featured postings, testimonials, institution enquiries, referrals, channel posts, sector pages, sitemap."""

import pathlib
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from career.config import settings
from career.db import Session, User
from career.main import app
from career import public_jobs, channel, growth
from tests.conftest import signup_member, CSRF
from tests.test_public_jobs import seed

POST = {
    "title": "Hydrologist, Early Warning Systems",
    "company": "Example Water Agency",
    "location": "Addis Ababa",
    "url": "https://example.org/careers/hydrologist",
    "description": "We are looking for a hydrologist to build flood early warning models with satellite rainfall estimates and gauge data across the Awash basin.",
    "deadline": (datetime.now(timezone.utc) + timedelta(days=20)).date().isoformat(),
    "contact_name": "Hiring Lead",
    "contact_email": "hr@example.org",
    "note": "Please feature for two weeks.",
}


def test_employer_posting_is_moderated_then_featured(client, monkeypatch):
    public_jobs.reset_cache()
    sent = []
    monkeypatch.setattr("career.notifications.email_send", lambda subject, text, to=None: sent.append((subject, to)))
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.org")
    monkeypatch.setattr(settings, "email_from", "owner@example.org")
    anon = TestClient(app)
    assert anon.post("/api/employers/post", json={**POST, "contact_email": "nope"}, headers=CSRF).status_code == 422
    r = anon.post("/api/employers/post", json=POST, headers=CSRF)
    assert r.status_code == 200 and r.json()["status"] == "received"
    assert sent and "featured vacancy request" in sent[0][0] and sent[0][1] == "owner@example.org"
    # Pending posts are not public.
    assert all(j["title"] != POST["title"] for j in anon.get("/api/public/jobs").json()["latest"])
    overview = client.get("/api/admin/overview").json()
    post = next(p for p in overview["employer_posts"] if p["title"] == POST["title"])
    assert post["status"] == "pending" and post["contact_email"] == "hr@example.org"
    approved = client.put(f"/api/admin/employer-posts/{post['id']}", json={"status": "approved"}).json()
    assert approved["status"] == "approved" and approved["featured_until"]
    d = anon.get("/api/public/jobs").json()
    first = d["latest"][0]
    assert first["title"] == POST["title"] and first["featured"] is True and first["source"] == "Featured employer" and "climate" in first["sectors"]
    assert d["featured"][0]["title"] == POST["title"]
    for private in ("contact_email", "hr@example.org", "Hiring Lead", "Please feature"):
        assert private not in anon.get("/api/public/jobs").text
    # Rejecting removes it again.
    client.put(f"/api/admin/employer-posts/{post['id']}", json={"status": "rejected"})
    assert all(j["title"] != POST["title"] for j in anon.get("/api/public/jobs").json()["latest"])


def test_testimonials_enquiries_and_referrals(client, monkeypatch):
    monkeypatch.setattr(settings, "landing_dir", pathlib.Path(__file__).resolve().parents[2] / "landing")
    from career import main as m
    m._landing_cache.update(at=0.0, html=None)
    public_jobs.reset_cache()
    anon = TestClient(app)
    assert "<section id=\"testimonials\" class=\"wrap reveal\" hidden>" in anon.get("/").text
    tr = client.post("/api/admin/testimonials", json={"name": "Ada L.", "role": "GIS analyst", "organisation": "Example NGO", "quote": "Found two roles I would have missed & the drafts were honest."})
    assert tr.status_code == 200, tr.text
    t = tr.json()
    m._landing_cache.update(at=0.0, html=None)
    page = anon.get("/").text
    assert "<section id=\"testimonials\" class=\"wrap reveal\">" in page and "Ada L." in page and "missed &amp; the drafts" in page
    assert anon.get("/api/public/testimonials").json()["testimonials"][0]["name"] == "Ada L."
    assert client.delete(f"/api/admin/testimonials/{t['id']}").json()["deleted"] and anon.get("/api/public/testimonials").json()["testimonials"] == []
    # Institution enquiry
    r = anon.post("/api/institutions/enquiry", json={"organisation": "Example University", "contact_name": "Dean", "contact_email": "dean@example.edu", "seats": 40, "note": "Career centre pilot"}, headers=CSRF)
    assert r.status_code == 200
    e = client.get("/api/admin/overview").json()["enquiries"][0]
    assert e["organisation"] == "Example University" and e["seats"] == 40
    # Referrals: fixed personal codes; a sign-up through one is attributed.
    member = signup_member(client)
    refs = member.get("/api/account/referrals").json()
    assert len(refs["invites"]) == settings.referral_invites and refs["referred"] == 0 and all(not i["used"] for i in refs["invites"])
    assert member.get("/api/account/referrals").json()["invites"][0]["code"] == refs["invites"][0]["code"]
    friend = TestClient(app)
    assert friend.post("/api/auth/signup", json={"email": "friend@example.org", "password": "friend-password-123", "invite": refs["invites"][0]["code"]}, headers=CSRF).status_code == 200
    refs = member.get("/api/account/referrals").json()
    assert refs["referred"] == 1 and refs["invites"][0]["used"] and refs["invites"][0]["joined_name"] == "friend"
    with Session() as db:
        me = db.query(User).filter_by(email="member@example.org").one()
        assert db.query(User).filter_by(email="friend@example.org").one().settings["referred_by"] == me.id
    assert next(u for u in client.get("/api/admin/overview").json()["users"] if u["email"] == "friend@example.org")["referred_by"] == me.id


def test_channel_posts_and_sector_pages(client, monkeypatch):
    public_jobs.reset_cache()
    with Session() as db:
        owner = db.query(User).filter_by(role="admin").one().id
        seed(db, owner, "a", url="https://example.org/jobs/a", title="Hydrologist", company="Water Org", location="Kenya")
        seed(db, owner, "b", url="https://example.org/jobs/b", title="GIS Analyst", deadline=(datetime.now(timezone.utc) + timedelta(days=3)).date().isoformat())
        seed(db, owner, "c", url="https://example.org/jobs/c", title="Data <Scientist>")
    sent = []
    monkeypatch.setattr("career.telegram.api", lambda method, **payload: sent.append((method, payload)) or {"message_id": 1})
    assert client.post("/api/admin/channel/post", json={"kind": "daily"}).status_code == 422  # not configured
    monkeypatch.setattr(settings, "telegram_bot_token", "123:abc")
    monkeypatch.setattr(settings, "telegram_channel_id", "@examplejobs")
    r = client.post("/api/admin/channel/post", json={"kind": "daily"}).json()
    assert r == {"posted": True, "kind": "daily", "roles": 3}
    method, payload = sent[0]
    assert method == "sendMessage" and payload["chat_id"] == "@examplejobs" and payload["parse_mode"] == "HTML"
    assert "Hydrologist" in payload["text"] and "Data &lt;Scientist&gt;" in payload["text"] and "Water Org · Kenya" in payload["text"] and "utm_source=telegram&amp;utm_medium=channel" in payload["text"] and "&utm_medium" not in payload["text"].replace("&amp;", "")
    # Nothing new: no second daily post. Weekly lists the closing role.
    assert client.post("/api/admin/channel/post", json={"kind": "daily"}).json()["posted"] is False
    assert client.post("/api/admin/channel/post", json={"kind": "weekly"}).json()["posted"] is True and "GIS Analyst" in sent[1][1]["text"]
    st = client.get("/api/admin/overview").json()["channel"]
    assert st["enabled"] and st["posts"] == 2 and st["last_daily"] and st["last_weekly"]
    # Sector pages, sitemap and robots.
    anon = TestClient(app)
    page = anon.get("/jobs/climate")
    assert page.status_code == 200 and "Hydrologist" in page.text and "GIS Analyst" not in page.text and '"@type": "JobPosting"' in page.text
    assert "Data &lt;Scientist&gt;" in anon.get("/jobs/data-science").text
    all_page = anon.get("/jobs").text
    assert "Hydrologist" in all_page and "GIS Analyst" in all_page and "Data &lt;Scientist&gt;" in all_page
    assert anon.get("/jobs/nope").status_code == 404
    sm = anon.get("/sitemap.xml")
    assert sm.status_code == 200 and "/jobs/gis-remote-sensing" in sm.text and sm.headers["content-type"].startswith("application/xml")
    assert "Sitemap:" in anon.get("/robots.txt").text and "Disallow: /app/" in anon.get("/robots.txt").text
