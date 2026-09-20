import json
import httpx
import pytest
from career.sources import collect, Context, parse_feed, iso
from career.config import settings

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>Example Jobs</title>
<item><title>Hydrologist</title><link>https://example.org/jobs/1</link><pubDate>Fri, 18 Sep 2026 10:00:00 +0000</pubDate><description>Short</description></item>
<item><title>GIS Analyst</title><link>https://example.org/jobs/2</link><description>%s</description></item>
</channel></rss>""" % (b"Long description " * 40)

RELIEFWEB_RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>ReliefWeb - Jobs</title>
<item><title>Climate Data Officer</title><link>https://reliefweb.int/job/99/climate-data-officer</link>
<pubDate>Fri, 18 Sep 2026 10:00:00 +0000</pubDate>
<description>&lt;div class="tag country"&gt;Country: Ethiopia&lt;/div&gt;&lt;div class="tag source"&gt;Organization: Example NGO&lt;/div&gt;&lt;div class="date closing"&gt;Closing date: 25 Sep 2026&lt;/div&gt;</description></item>
<item><title>Known Job</title><link>https://reliefweb.int/job/1/known</link><description></description></item>
</channel></rss>"""

PAGE = b"<html><body><nav>Menu</nav><main><h1>Climate Data Officer</h1><p>Analyse hydrological and climate data with Python and GIS tools for programmes in Ethiopia.</p></main><footer>x</footer></body></html>"


REAL_CLIENT = httpx.Client


def mock(monkeypatch, handler):
    monkeypatch.setattr(
        "career.sources.httpx.Client",
        lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(handler), **kw),
    )


def test_greenhouse_contract(monkeypatch):
    def handler(request):
        assert str(request.url).startswith("https://boards-api.greenhouse.io/v1/boards/example/jobs")
        return httpx.Response(200, json={"jobs": [{"id": 123, "title": "Data Scientist", "location": {"name": "Remote"}, "content": "<p>Build climate models with Python and geospatial observations.</p>", "absolute_url": "https://example.org/jobs/123", "updated_at": "2026-09-01T00:00:00Z"}]})

    mock(monkeypatch, handler)
    jobs, ids = collect({"kind": "greenhouse", "value": "example"})
    assert jobs[0]["external_id"] == "example:123" and "<p>" not in jobs[0]["description"]
    assert jobs[0]["posted"].startswith("2026-09-01")


def test_lever_includes_requirement_lists(monkeypatch):
    def handler(request):
        return httpx.Response(200, json=[{"id": "abc", "text": "Research Scientist", "descriptionPlain": "Develop climate data products using Python.", "categories": {"location": "Remote"}, "lists": [{"text": "Requirements", "content": "<li>Experience with hydrology required.</li>"}], "hostedUrl": "https://example.org/jobs/abc", "createdAt": 1758000000000}])

    mock(monkeypatch, handler)
    jobs, _ = collect({"kind": "lever", "value": "example"})
    assert "hydrology required" in jobs[0]["description"]
    assert jobs[0]["posted"].startswith("2025") or jobs[0]["posted"].startswith("2026")


def test_workable_lists_then_details_and_skips_known(monkeypatch):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if request.method == "POST":
            return httpx.Response(200, json={"total": 2, "results": [
                {"shortcode": "AAA", "title": "GIS Specialist", "location": {"city": "Nairobi", "country": "Kenya"}, "workplace": "hybrid", "published": "2026-09-10T00:00:00.000Z"},
                {"shortcode": "BBB", "title": "Known", "location": {}, "workplace": "remote"},
            ]})
        return httpx.Response(200, json={"description": "<p>Map climate risk with geospatial tools.</p>", "requirements": "<ul><li>GIS</li></ul>", "benefits": ""})

    mock(monkeypatch, handler)
    ctx = Context(known_urls={"https://apply.workable.com/acme/j/BBB/"}, delay=0)
    jobs, _ = collect({"kind": "workable", "value": "acme"}, ctx=ctx)
    assert jobs[0]["location"] == "Nairobi, Kenya" and "GIS" in jobs[0]["description"]
    assert jobs[1] == {"url": "https://apply.workable.com/acme/j/BBB/", "partial": True}
    assert sum("/api/v2/" in c for c in calls) == 1


def test_smartrecruiters_uses_detail_sections(monkeypatch):
    def handler(request):
        url = str(request.url)
        if "/postings/" in url:
            return httpx.Response(200, json={"applyUrl": "https://jobs.smartrecruiters.com/Acme/1?apply", "jobAd": {"sections": {"jobDescription": {"title": "Job", "text": "<p>Hydrology modelling in Python.</p>"}, "qualifications": {"title": "Qualifications", "text": "MSc"}}}})
        return httpx.Response(200, json={"totalFound": 1, "content": [{"id": "1", "name": "Hydrologist", "ref": "https://api.smartrecruiters.com/v1/companies/Acme/postings/1", "location": {"city": "Addis Ababa", "country": "Ethiopia", "remote": False}, "releasedDate": "2026-09-01T00:00:00.000Z", "company": {"name": "Acme"}}]})

    mock(monkeypatch, handler)
    jobs, _ = collect({"kind": "smartrecruiters", "value": "Acme"})
    assert jobs[0]["title"] == "Hydrologist" and "Qualifications" in jobs[0]["description"]
    assert jobs[0]["location"] == "Addis Ababa, Ethiopia"


def test_ashby_and_remotive(monkeypatch):
    def handler(request):
        if "ashbyhq" in str(request.url):
            return httpx.Response(200, json={"jobs": [{"id": "x", "title": "ML Engineer", "location": "Remote", "isRemote": True, "descriptionPlain": "Train models on climate datasets with machine learning.", "jobUrl": "https://jobs.ashbyhq.com/acme/x", "publishedAt": "2026-09-01T00:00:00+00:00", "isListed": True}]})
        return httpx.Response(200, json={"jobs": [{"id": 5, "title": "Data Scientist", "company_name": "Remote Co", "candidate_required_location": "Africa", "description": "<p>Remote sensing pipelines.</p>", "url": "https://remotive.com/remote-jobs/data/5", "publication_date": "2026-09-01T00:00:00"}]})

    mock(monkeypatch, handler)
    ashby, _ = collect({"kind": "ashby", "value": "acme"})
    assert ashby[0]["location"].startswith("Remote")
    remotive, _ = collect({"kind": "remotive", "value": "data"})
    assert remotive[0]["location"] == "Remote, Africa" and remotive[0]["source"] == "Remotive"


def test_reliefweb_uses_v2_when_appname_set(monkeypatch):
    monkeypatch.setattr(settings, "reliefweb_appname", "test-app")

    def handler(request):
        assert str(request.url).startswith("https://api.reliefweb.int/v2/jobs")
        assert "appname=test-app" in str(request.url) and "query%5Boperator%5D=OR" in str(request.url)
        return httpx.Response(200, json={"data": [{"id": 7, "fields": {"title": "Climate Analyst", "body": "Analyse climate data.", "how_to_apply": "Email us.", "url": "https://reliefweb.int/job/7", "date": {"closing": "2026-10-01T00:00:00+00:00", "created": "2026-09-01T00:00:00+00:00"}, "country": [{"name": "Ethiopia"}], "source": [{"name": "Example NGO"}], "type": [{"name": "Consultancy"}]}}]})

    mock(monkeypatch, handler)
    jobs, _ = collect({"kind": "reliefweb", "value": ""})
    assert jobs[0]["deadline"].startswith("2026-10-01") and jobs[0]["location"] == "Ethiopia"
    assert "How to apply" in jobs[0]["description"] and "Consultancy" in jobs[0]["description"]


def test_reliefweb_rss_fallback_reads_pages_within_budget(monkeypatch):
    monkeypatch.setattr(settings, "reliefweb_appname", "")
    fetched = []

    def handler(request):
        url = str(request.url)
        if "rss.xml" in url:
            assert "search=climate" in url
            return httpx.Response(200, content=RELIEFWEB_RSS, headers={"content-type": "application/rss+xml"})
        fetched.append(url)
        return httpx.Response(200, content=PAGE, headers={"content-type": "text/html"})

    mock(monkeypatch, handler)
    ctx = Context(known_urls={"https://reliefweb.int/job/1/known"}, page_budget=5, delay=0)
    jobs, _ = collect({"kind": "reliefweb", "value": "climate"}, ctx=ctx)
    # Page fetches are pinned to the validated address; the path is what matters here.
    assert [httpx.URL(u).path for u in fetched] == ["/job/99/climate-data-officer"]
    assert jobs[0]["company"] == "Example NGO" and jobs[0]["location"] == "Ethiopia"
    assert jobs[0]["deadline"] == "2026-09-25" and "Menu" not in jobs[0]["description"]
    assert jobs[1]["partial"] is True
    ctx2 = Context(known_urls={"https://reliefweb.int/job/1/known"}, page_budget=0, delay=0)
    jobs2, _ = collect({"kind": "reliefweb", "value": "climate"}, ctx=ctx2)
    assert jobs2 == [{"url": "https://reliefweb.int/job/1/known", "partial": True}] and ctx2.skipped_for_budget == 1


def test_generic_rss_completes_short_entries(monkeypatch):
    def handler(request):
        if str(request.url).endswith("feed.xml"):
            return httpx.Response(200, content=RSS, headers={"content-type": "application/xml"})
        return httpx.Response(200, content=PAGE, headers={"content-type": "text/html"})

    mock(monkeypatch, handler)
    jobs, _ = collect({"kind": "rss", "value": "https://example.org/feed.xml"}, ctx=Context(delay=0))
    assert jobs[0]["title"] == "Hydrologist" and "hydrological" in jobs[0]["description"]
    assert jobs[1]["description"].startswith("Long description") and jobs[0]["source"] == "RSS: example.org"


def test_rss_rejects_non_feed(monkeypatch):
    mock(monkeypatch, lambda request: httpx.Response(200, content=b"<html>not a feed</html>"))
    with pytest.raises(ValueError, match="feed"):
        collect({"kind": "rss", "value": "https://example.org/page"})
    with pytest.raises(ValueError):
        collect({"kind": "rss", "value": "javascript:alert(1)"})


def test_page_connector_only_accepts_real_links(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "fake")
    from career.sources import PageListings, PageListing

    def structured(model, schema, instructions, data):
        assert any(l["href"] == "https://example.org/careers/1" for l in data["links"])
        return PageListings(jobs=[PageListing(title="Hydrologist", url="https://example.org/careers/1", location="Ethiopia"), PageListing(title="Invented", url="https://example.org/careers/999")])

    monkeypatch.setattr("career.sources.structured", structured)

    def handler(request):
        if str(request.url).endswith("/careers"):
            return httpx.Response(200, content=b'<html><body><main><a href="/careers/1">Hydrologist</a><a href="/about">About</a></main></body></html>', headers={"content-type": "text/html"})
        return httpx.Response(200, content=PAGE, headers={"content-type": "text/html"})

    mock(monkeypatch, handler)
    jobs, _ = collect({"kind": "page", "value": "https://example.org/careers"}, ctx=Context(delay=0))
    assert [j["title"] for j in jobs] == ["Hydrologist"] and jobs[0]["source"] == "Page: example.org"


def test_page_connector_requires_ai(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "")
    with pytest.raises(ValueError, match="AI"):
        collect({"kind": "page", "value": "https://example.org/careers"})


def test_feed_parsing_and_dates():
    title, entries = parse_feed(b'<feed xmlns="http://www.w3.org/2005/Atom"><title>T</title><entry><title>A</title><link rel="alternate" href="https://e.org/a"/><updated>2026-09-01T00:00:00Z</updated><summary>s</summary></entry></feed>')
    assert title == "T" and entries[0]["link"] == "https://e.org/a"
    assert iso("Fri, 18 Sep 2026 10:00:00 +0000").startswith("2026-09-18")
    assert iso(1758000000000) is not None and iso("2026-09-01") == "2026-09-01" and iso("junk") is None


def test_transient_transport_errors_are_retried(monkeypatch):
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) < 2:
            raise httpx.RemoteProtocolError("peer closed connection")
        return httpx.Response(200, json={"jobs": []})

    mock(monkeypatch, handler)
    monkeypatch.setattr("career.sources.time.sleep", lambda s: None)
    jobs, _ = collect({"kind": "greenhouse", "value": "example"})
    assert jobs == [] and len(calls) == 2

    def always(request):
        raise httpx.ReadTimeout("slow")

    mock(monkeypatch, always)
    with pytest.raises(ValueError, match="closed the connection"):
        collect({"kind": "greenhouse", "value": "example"})
