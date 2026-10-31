"""Public search pages by place and field, structured data, and site measurement."""

import json
import re
from fastapi.testclient import TestClient
from career.db import Session, User
from career.main import app
from career import public_jobs, business_report
from tests.test_public_jobs import seed

BROWSER = {"user-agent": "Mozilla/5.0 (Windows NT 10.0) Firefox/130.0"}
FROM_GOOGLE = {**BROWSER, "referer": "https://www.google.com/"}


def seed_places(client):
    public_jobs.reset_cache()
    with Session() as db:
        owner = db.query(User).filter_by(role="admin").one().id
        for n in range(3):
            seed(db, owner, f"et{n}", url=f"https://example.org/jobs/et{n}", title=f"Climate Data Scientist {n}", location="Addis Ababa, Ethiopia")
        seed(db, owner, "ke", url="https://example.org/jobs/ke", title="GIS Analyst", location="Nairobi, Kenya")
        seed(db, owner, "rm", url="https://example.org/jobs/rm", title="Data Engineer", location="Remote")


def ld_blocks(page):
    return [json.loads(b) for b in re.findall(r'<script type="application/ld\+json">(.*?)</script>', page, re.S)]


def test_place_and_field_pages_list_only_their_jobs(client):
    seed_places(client)
    anon = TestClient(app, headers=BROWSER)
    page = anon.get("/jobs/in/ethiopia").text
    assert "Jobs in Ethiopia" in page and "Climate Data Scientist 0" in page and "GIS Analyst" not in page
    assert 'href="/jobs/climate/in/ethiopia"' in page
    blocks = ld_blocks(page)
    jobs = next(b for b in blocks if b["@type"] == "ItemList")["itemListElement"]
    assert jobs[0]["item"]["jobLocation"]["address"]["addressCountry"] == "ET"
    assert [c["name"] for c in next(b for b in blocks if b["@type"] == "BreadcrumbList")["itemListElement"]] == ["Jobs", "Ethiopia"]

    combo = anon.get("/jobs/climate/in/ethiopia").text
    assert "Climate, hydrology and water jobs in Ethiopia" in combo and "Climate Data Scientist 2" in combo
    remote = anon.get("/jobs/in/remote").text
    assert "Remote jobs in data" in remote and "Data Engineer" in remote and "Addis Ababa" not in remote
    # Unknown places, fields, and places without jobs are not pages.
    assert anon.get("/jobs/in/atlantis").status_code == 404
    assert anon.get("/jobs/in/peru").status_code == 404
    assert anon.get("/jobs/nonsense/in/ethiopia").status_code == 404

    # The job index offers the places; the sitemap lists them, field-and-place pages only with enough jobs.
    assert 'href="/jobs/in/ethiopia"' in anon.get("/jobs").text
    sitemap = anon.get("/sitemap.xml").text
    assert "/jobs/in/ethiopia</loc>" in sitemap and "/jobs/in/kenya</loc>" in sitemap and "/jobs/in/remote</loc>" in sitemap
    assert "/jobs/climate/in/ethiopia</loc>" in sitemap and "/jobs/gis-remote-sensing/in/kenya</loc>" not in sitemap


def test_job_page_has_one_job_posting_and_measures_clicks(client):
    seed_places(client)
    anon = TestClient(app, headers=FROM_GOOGLE)
    job = next(j for j in anon.get("/api/public/jobs").json()["latest"] if j["title"] == "GIS Analyst")
    page = anon.get("/job/" + job["slug"]).text
    posting = next(b for b in ld_blocks(page) if b["@type"] == "JobPosting")
    assert posting["@context"] == "https://schema.org" and posting["directApply"] is False and posting["jobLocation"]["address"]["addressCountry"] == "KE"
    assert 'href="/jobs/in/kenya"' in page
    out = anon.get("/out/" + job["slug"], follow_redirects=False)
    assert out.status_code == 302 and out.headers["location"] == "https://example.org/jobs/ke"
    match = anon.get("/match/" + job["slug"], follow_redirects=False)
    assert match.headers["location"] == "/app/?job_url=https%3A%2F%2Fexample.org%2Fjobs%2Fke"
    # Unknown slugs never redirect off the site.
    assert anon.get("/out/not-a-job", follow_redirects=False).headers["location"] == "/jobs"
    # Crawlers are not counted.
    crawler = TestClient(app, headers={"user-agent": "Googlebot/2.1", "referer": "https://www.google.com/"})
    crawler.get("/job/" + job["slug"])
    crawler.get("/out/" + job["slug"], follow_redirects=False)
    TestClient(app, headers=BROWSER).get("/jobs/in/kenya")

    site = client.get("/api/admin/business").json()["site"]
    assert site["views"] == {"job": 1, "place": 1} and site["search"] == {"job": 1} and site["engines"] == {"google": 1}
    assert site["apply"] == {"job": 1} and site["match"] == {"job": 1} and site["job_page_click_through"] == 2.0


def test_business_report_prints_site_section(client, capsys):
    seed_places(client)
    TestClient(app, headers=FROM_GOOGLE).get("/jobs/in/ethiopia")
    business_report.main()
    out = capsys.readouterr().out
    assert "Public site, last 30 days (people, not crawlers): 1 page views, 1 from search engines" in out and "by engine: google 1" in out
