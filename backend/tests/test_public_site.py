"""Public site: job pages with sharing, searchable index with filters and pagination, organisations, guide, sitemap, details extraction."""

import pathlib
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from career.config import settings
from career.db import Session, User
from career.main import app
from career import public_jobs, public_site
from tests.conftest import CSRF
from tests.test_public_jobs import seed


def test_details_extraction_and_classification():
    salary, contract, work = public_jobs.extract_details("Senior Data Scientist (Remote)", "Full-time position. Salary: USD 3,500 per month. Work from home allowed.")
    assert salary == "USD 3,500 per month" and contract == "Full-time" and work == "Remote"
    assert public_jobs.extract_details("Consultancy: El Niño research", "Call for proposals, 45,000 ETB, 3 months. Hybrid in Addis.")[:3] == ("45,000 ETB", "Consultancy", "Hybrid")
    assert public_jobs.extract_details("Officer", "No money mentioned here at all.") == (None, None, None)
    assert public_jobs.location_class("Addis Ababa, Ethiopia") == "ethiopia" and public_jobs.location_class("Nairobi, Kenya") == "africa"
    assert public_jobs.location_class("Remote, LATAM") == "remote" and public_jobs.location_class("Geneva") == "other"
    assert public_jobs.job_slug("GIS & Remote Sensing Analyst!", "https://x/1") != public_jobs.job_slug("GIS & Remote Sensing Analyst!", "https://x/2")
    assert public_jobs.job_slug("GIS & Remote Sensing Analyst!", "https://x/1").startswith("gis-remote-sensing-analyst-")
    assert public_jobs.ago((datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()) == "5h ago"
    assert public_jobs.ago((datetime.now(timezone.utc) - timedelta(days=3)).isoformat()) == "3 days ago"


def _seed_many(client):
    public_jobs.reset_cache()
    with Session() as db:
        owner = db.query(User).filter_by(role="admin").one().id
        for i in range(30):
            seed(db, owner, f"j{i}", url=f"https://example.org/jobs/{i}", title=f"Data Analyst {i}" if i % 2 == 0 else f"Hydrologist {i}", company="Water Org" if i % 3 == 0 else f"Org {i}", location="Addis Ababa, Ethiopia" if i % 2 else "Remote", posted=(datetime.now(timezone.utc) - timedelta(hours=i)).isoformat(), description="Full-time role paying USD 2,000 per month. " * 3)
        seed(db, owner, "soon", url="https://example.org/jobs/soon", title="MEL Officer", company="Water Org", deadline=(datetime.now(timezone.utc) + timedelta(days=3)).date().isoformat())


def test_jobs_index_search_filters_and_pagination(client):
    _seed_many(client)
    anon = TestClient(app)
    page = anon.get("/jobs").text
    assert "31 postings" in page and "Page 1 of 2" in page and "Next →" in page and page.count('class="job-item"') == 24
    page2 = anon.get("/jobs?page=2").text
    assert page2.count('class="job-item"') == 7 and "← Previous" in page2
    assert "1 posting" in anon.get("/jobs?q=mel").text and "MEL Officer" in anon.get("/jobs?q=mel").text
    hydro = anon.get("/jobs?sector=climate").text
    assert "Hydrologist" in hydro and "Data Analyst" not in hydro and "Climate, hydrology and water jobs" in hydro
    eth = anon.get("/jobs?location=ethiopia").text
    assert "Remote" not in eth.split('class="job-list"')[1].split("</div>")[0] and "Addis Ababa" in eth
    org = anon.get("/jobs?org=water-org").text
    assert "Open roles at Water Org" in org and "11 postings" in org
    assert "MEL Officer" in anon.get("/jobs?closing=7").text and "1 posting" in anon.get("/jobs?closing=7").text
    assert "USD 2,000 per month" in page and "Full-time" in page and "h ago" in page
    assert anon.get("/jobs/nope").status_code == 404


def test_job_page_with_sharing_related_roles_and_structured_data(client, monkeypatch):
    _seed_many(client)
    monkeypatch.setattr(settings, "telegram_channel_id", "@jobs_find_ai_alerts")
    anon = TestClient(app)
    d = anon.get("/api/public/jobs").json()
    job = next(j for j in d["latest"] if j["salary"])
    assert "body" not in job and job["slug"] and job["salary"] == "USD 2,000 per month" and job["contract"] == "Full-time"
    r = anon.get("/job/" + job["slug"])
    assert r.status_code == 200
    page = r.text
    assert job["title"] in page and 'href="https://example.org/jobs/' in page and "Apply on the employer" in page
    assert "t.me/share/url?" in page and "wa.me/?" in page and "linkedin.com/sharing" in page and "Copy link" in page
    assert '"@type": "JobPosting"' in page and '"employmentType": "FULL_TIME"' in page and '"jobLocationType": "TELECOMMUTE"' in page
    assert "Similar roles" in page and "Join on Telegram" in page and "t.me/jobs_find_ai_alerts" in page
    assert "See how you match" in page and "/app/?job_url=https%3A%2F%2Fexample.org" in page
    assert anon.get("/job/does-not-exist-abc123").status_code == 404
    # Landing cards now link to job pages.
    assert f'href="/job/{job["slug"]}"' in anon.get("/jobs").text


def test_organisations_guide_and_sitemap(client):
    _seed_many(client)
    anon = TestClient(app)
    idx = anon.get("/organisations").text
    assert "Water Org" in idx and "11 open roles" in idx and 'href="/organisations/water-org"' in idx
    org = anon.get("/organisations/water-org")
    assert org.status_code == 200 and "Jobs at Water Org" in org.text and org.text.count('class="job-item"') == 11
    assert anon.get("/organisations/nope").status_code == 404
    g = anon.get("/guide").text
    assert "Job seeker's guide" in g and "cv-that-survives-screening" in g
    a = anon.get("/guide/cv-that-survives-screening")
    assert a.status_code == 200 and "Lead with verifiable facts" in a.text and '"@type": "Article"' in a.text and "Request an invite" in a.text
    assert anon.get("/guide/nope").status_code == 404
    sm = anon.get("/sitemap.xml").text
    assert "/organisations/water-org" in sm and "/guide/interviews-for-data-and-climate-roles" in sm and "/job/" in sm and sm.count("<url>") > 40


def test_channel_digest_links_to_job_pages(client, monkeypatch):
    _seed_many(client)
    sent = []
    monkeypatch.setattr("career.telegram.api", lambda method, **payload: sent.append(payload) or {"message_id": 1})
    monkeypatch.setattr(settings, "telegram_bot_token", "123:abc")
    monkeypatch.setattr(settings, "telegram_channel_id", "@jobs_find_ai_alerts")
    assert client.post("/api/admin/channel/post", json={"kind": "daily"}).json()["posted"]
    assert "/job/" in sent[0]["text"] and "utm_source=telegram&amp;utm_medium=channel" in sent[0]["text"] and "example.org/jobs/" not in sent[0]["text"]


def test_landing_banner_and_guide_links(client, monkeypatch):
    monkeypatch.setattr(settings, "landing_dir", pathlib.Path(__file__).resolve().parents[2] / "landing")
    monkeypatch.setattr(settings, "telegram_channel_id", "@jobs_find_ai_alerts")
    from career import main as m
    m._landing_cache.update(at=0.0, html=None)
    page = TestClient(app).get("/").text
    assert 'class="banner"' in page and "Join on Telegram" in page and "<!--CHANNEL-BANNER-->" not in page and 'href="/guide"' in page and 'href="/jobs"' in page
