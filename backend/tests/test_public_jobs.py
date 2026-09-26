"""Public job listings: public boards only, public facts only, deduplicated across members, rendered into the landing page."""

import pathlib
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from career.config import settings
from career.db import Session, User, put
from career.main import app
from career import public_jobs
from tests.conftest import signup_member
from tests.test_workflow import JOB


def seed(db, user_id, key, **over):
    data = {**JOB, "status": "new", "match": None, "created": datetime.now(timezone.utc).isoformat(), "last_seen": datetime.now(timezone.utc).isoformat(), "source": "ReliefWeb", "posted": datetime.now(timezone.utc).isoformat(), "screen": {"title_hits": ["data"]}, **over}
    return put(db, "job", "job:" + key, data, user_id=user_id)


def test_public_listings_show_public_facts_only(client):
    public_jobs.reset_cache()
    member = signup_member(client)
    with Session() as db:
        owner = db.query(User).filter_by(role="admin").one().id
        mem = db.query(User).filter_by(role="member").one().id
        soon = (datetime.now(timezone.utc) + timedelta(days=4)).date().isoformat()
        seed(db, owner, "a", url="https://example.org/jobs/a", title="Hydrologist", match={"score": 88, "summary": "private"})
        seed(db, mem, "a2", url="https://example.org/jobs/a/", title="Hydrologist", match={"score": 40})  # same posting, other member
        seed(db, owner, "b", url="https://example.org/jobs/b", title="GIS Analyst", deadline=soon)
        seed(db, owner, "c", url="https://example.org/jobs/c", title="From my inbox", source="Email alert")
        seed(db, owner, "d", url="https://example.org/jobs/d", title="Pasted by hand", source="Manual")
        seed(db, owner, "e", url="https://example.org/jobs/e", title="Expired role", deadline="2020-01-01")
        seed(db, owner, "f", url="https://example.org/jobs/f", title="Stale role", last_seen=(datetime.now(timezone.utc) - timedelta(days=40)).isoformat())
        seed(db, owner, "g", url="https://example.org/jobs/g", title="Archived role", status="archived")
        seed(db, owner, "h", url="https://example.org/jobs/h", title="Country Director", screen={"title_hits": []}, match={"score": 20})
        seed(db, owner, "i", url="https://example.org/jobs/i", title="Evaluated but generic title", screen={"title_hits": []}, match={"score": 66})
    anon = TestClient(app)
    d = anon.get("/api/public/jobs").json()
    titles = [j["title"] for j in d["latest"]]
    assert titles.count("Hydrologist") == 1 and "GIS Analyst" in titles and "Evaluated but generic title" in titles
    for hidden in ("From my inbox", "Pasted by hand", "Expired role", "Stale role", "Archived role", "Country Director"):
        assert hidden not in titles
    assert [j["title"] for j in d["featured"]] == ["Hydrologist"]
    assert [j["title"] for j in d["closing_soon"]] == ["GIS Analyst"]
    assert d["total"] == 3 and d["listed_last_7_days"] == 3
    body = anon.get("/api/public/jobs").text
    for private in ("score", "summary", "match", "user_id", "status", "private", "Example Applicant"):
        assert private not in body
    assert set(d["latest"][0]) == {"title", "company", "location", "source", "posted", "deadline", "url", "excerpt", "featured", "sectors", "slug", "org_slug", "location_class", "salary", "contract", "work_type"}
    assert "_all" not in d
    assert member.get("/api/state").json()["jobs"]  # member data untouched


def test_landing_page_renders_latest_jobs_and_structured_data(client, monkeypatch):
    public_jobs.reset_cache()
    monkeypatch.setattr(settings, "landing_dir", pathlib.Path(__file__).resolve().parents[2] / "landing")
    from career import main as m
    m._landing_cache.update(at=0.0, html=None)
    with Session() as db:
        owner = db.query(User).filter_by(role="admin").one().id
        seed(db, owner, "x", url="https://example.org/jobs/x?utm=1", title="Climate <Risk> Analyst", company="Example & Co", deadline=(datetime.now(timezone.utc) + timedelta(days=2)).date().isoformat())
    page = TestClient(app).get("/")
    assert page.status_code == 200 and "text/html" in page.headers["content-type"]
    assert "Climate &lt;Risk&gt; Analyst" in page.text and "Example &amp; Co" in page.text and "Closes in 2 days" in page.text
    assert "<!--JOBS-->" not in page.text and "<!--JOBS-JSONLD-->" not in page.text
    assert '"@type": "JobPosting"' in page.text and '"validThrough"' in page.text
    assert "<script>" not in page.text.split("application/ld+json")[1].split("</script>")[0]


def test_landing_page_without_landing_dir_is_404(client, monkeypatch):
    monkeypatch.setattr(settings, "landing_dir", pathlib.Path("does-not-exist"))
    from career import main as m
    m._landing_cache.update(at=0.0, html=None)
    assert TestClient(app).get("/").status_code == 404


def test_search_console_tag_is_injected_when_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "landing_dir", pathlib.Path(__file__).resolve().parents[2] / "landing")
    from career import main as m
    m._landing_cache.update(at=0.0, html=None)
    assert "google-site-verification" not in TestClient(app).get("/").text
    monkeypatch.setattr(settings, "google_site_verification", 'abc"123')
    m._landing_cache.update(at=0.0, html=None)
    page = TestClient(app).get("/").text
    assert '<meta name="google-site-verification" content="abc&quot;123" />' in page and page.index("google-site-verification") < page.index("<body")


def test_channel_link_appears_when_a_public_channel_is_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "landing_dir", pathlib.Path(__file__).resolve().parents[2] / "landing")
    from career import main as m
    m._landing_cache.update(at=0.0, html=None)
    assert "t.me/" not in TestClient(app).get("/").text
    monkeypatch.setattr(settings, "telegram_channel_id", "@jobs_find_ai_alerts")
    m._landing_cache.update(at=0.0, html=None)
    page = TestClient(app).get("/").text
    assert page.count('href="https://t.me/jobs_find_ai_alerts"') == 2 and "Join on Telegram" in page and "<!--CHANNEL-BANNER-->" not in page
