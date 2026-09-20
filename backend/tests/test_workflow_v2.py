from career.db import Session, Record, put
from career.config import settings
from career.schemas import Package, QualityReview
from career.ai import write_package
from tests.test_workflow import JOB, verified_profile


def test_preferences_only_invalidate_matches_when_relevant(client):
    verified_profile(client)
    j = client.post("/api/jobs", json=JOB).json()
    client.post(f"/api/jobs/{j['id']}/match")
    prefs = client.get("/api/state").json()["preferences"]
    client.put("/api/preferences", json={**prefs, "min_score": 55, "alerts_enabled": True, "notify_channels": ["telegram"]})
    assert client.get("/api/state").json()["jobs"][0]["match"] is not None
    client.put("/api/preferences", json={**prefs, "keywords": ["hydrology"]})
    assert client.get("/api/state").json()["jobs"][0]["match"] is None


def test_profile_save_without_evidence_change_keeps_matches(client):
    p = verified_profile(client)
    j = client.post("/api/jobs", json=JOB).json()
    client.post(f"/api/jobs/{j['id']}/match")
    client.put("/api/profile", json={**p, "headline": "New headline"})
    assert client.get("/api/state").json()["jobs"][0]["match"] is not None
    p["facts"][0]["verified"] = False
    client.put("/api/profile", json=p)
    assert client.get("/api/state").json()["jobs"][0]["match"] is None


def test_state_lists_jobs_without_descriptions_and_detail_has_them(client):
    j = client.post("/api/jobs", json=JOB).json()
    listed = client.get("/api/state").json()["jobs"][0]
    assert "description" not in listed and listed["description_preview"].startswith("Build Python")
    assert client.get(f"/api/jobs/{j['id']}").json()["description"] == JOB["description"]
    assert client.get("/api/jobs/nope").status_code == 404


def test_scan_screens_prioritises_alerts_and_archives(client, monkeypatch):
    verified_profile(client)
    client.post("/api/sources", json={"kind": "greenhouse", "value": "example"})
    feed = [
        JOB,
        {**JOB, "title": "Senior Data Scientist, climate machine learning", "url": "https://example.org/jobs/2", "description": "Lead machine learning for climate services in Ethiopia with Python. " * 2},
        {**JOB, "title": "Chef", "url": "https://example.org/jobs/3", "description": "Cook meals in a busy kitchen. No analytics."},
    ]
    monkeypatch.setattr("career.service.collect", lambda *a, **k: (feed, []))
    monkeypatch.setattr(settings, "openai_api_key", "fake-test-key")
    monkeypatch.setattr(settings, "max_matches_per_run", 1)
    monkeypatch.setattr("career.service.match_job", lambda profile, job, prefs: {"score": 90, "summary": "Strong", "requirements": [], "strengths": ["Python"], "gaps": [], "mode": "ai"})
    prefs = client.get("/api/state").json()["preferences"]
    client.put("/api/preferences", json={**prefs, "alerts_enabled": True, "notify_channels": []})
    client.post("/api/scan")
    state = client.get("/api/state").json()
    titles = {j["title"] for j in state["jobs"]}
    assert "Chef" not in titles and len(state["jobs"]) == 2
    run = state["runs"][0]
    assert run["status"] == "completed" and run["matched"] == 1 and run["sources"][0]["relevant"] == 2
    evaluated = [j for j in state["jobs"] if j["match"]]
    assert evaluated[0]["title"].startswith("Senior Data Scientist")  # most title hits ranks first
    assert run["alerts"] == 1 and state["inbox_unread"] == 1
    assert any("await evaluation" in w for w in run["warnings"])
    client.post("/api/scan")
    state = client.get("/api/state").json()
    assert state["runs"][0]["alerts"] == 1 and state["inbox_unread"] == 2
    assert client.post("/api/inbox/read", json={"job_ids": []}).json()["read"] == 2
    assert client.get("/api/state").json()["inbox_unread"] == 0
    # A posting absent from every feed for a long time is archived; shortlisted ones are kept.
    with Session() as db:
        for row in db.query(Record).filter_by(kind="job").all():
            put(db, "job", row.key, {**row.data, "last_seen": "2020-01-01T00:00:00+00:00"}, user_id=row.user_id)
        saved = db.query(Record).filter_by(kind="job").first()
        put(db, "job", saved.key, {**saved.data, "status": "saved"}, user_id=saved.user_id)
    monkeypatch.setattr("career.service.collect", lambda *a, **k: ([], []))
    client.post("/api/scan")
    statuses = sorted(j["status"] for j in client.get("/api/state").json()["jobs"])
    assert statuses == ["archived", "saved"]


def test_failed_evaluations_back_off(client, monkeypatch):
    verified_profile(client)
    client.post("/api/sources", json={"kind": "greenhouse", "value": "example"})
    monkeypatch.setattr("career.service.collect", lambda *a, **k: ([JOB], []))
    monkeypatch.setattr(settings, "openai_api_key", "fake-test-key")
    calls = []

    def boom(*a):
        calls.append(1)
        raise RuntimeError("model down")

    monkeypatch.setattr("career.service.match_job", boom)
    for _ in range(4):
        client.post("/api/scan")
    assert len(calls) == 3
    job = client.get("/api/state").json()["jobs"][0]
    assert job["match_attempts"] == 3 and job["match"] is None


def test_digest_alert_sends_one_message(client, monkeypatch):
    verified_profile(client)
    client.post("/api/sources", json={"kind": "greenhouse", "value": "example"})
    feed = [JOB, {**JOB, "title": "Climate Analyst", "url": "https://example.org/jobs/2"}]
    monkeypatch.setattr("career.service.collect", lambda *a, **k: (feed, []))
    monkeypatch.setattr(settings, "openai_api_key", "fake-test-key")
    monkeypatch.setattr("career.service.match_job", lambda *a: {"score": 95, "summary": "S", "requirements": [], "strengths": [], "gaps": [], "mode": "ai"})
    monkeypatch.setattr("career.notifications.availability", lambda db=None: {"telegram": True})
    monkeypatch.setattr("career.notifications.telegram_chat", lambda db=None: "1")
    sent = []
    monkeypatch.setattr("career.notifications.telegram_send", lambda chat, text, job_id=None: sent.append(text))
    prefs = client.get("/api/state").json()["preferences"]
    client.put("/api/preferences", json={**prefs, "alerts_enabled": True, "notify_channels": ["telegram"], "alert_mode": "digest"})
    client.post("/api/scan")
    assert len(sent) == 1 and "2 new matching" in sent[0] and "Climate Analyst" in sent[0]
    run = client.get("/api/state").json()["runs"][0]
    assert run["alerts"] == 2 and run["delivered"]["telegram"] == "accepted"
    client.post("/api/scan")
    assert len(sent) == 1


def test_email_is_bundled_while_telegram_stays_per_job(client, monkeypatch):
    verified_profile(client)
    client.post("/api/sources", json={"kind": "greenhouse", "value": "example"})
    feed = [JOB, {**JOB, "title": "Climate Analyst", "url": "https://example.org/jobs/2"}, {**JOB, "title": "GIS Lead", "url": "https://example.org/jobs/3"}]
    monkeypatch.setattr("career.service.collect", lambda *a, **k: (feed, []))
    monkeypatch.setattr(settings, "openai_api_key", "fake-test-key")
    monkeypatch.setattr("career.service.match_job", lambda *a: {"score": 95, "summary": "S", "requirements": [], "strengths": ["fit"], "gaps": [], "mode": "ai"})
    monkeypatch.setattr("career.notifications.availability", lambda db=None: {"telegram": True, "email": True})
    monkeypatch.setattr("career.service.notify_ready", lambda db=None: {"telegram": True, "email": True})
    monkeypatch.setattr("career.notifications.telegram_chat", lambda db=None: "1")
    telegram_sent, emails = [], []
    monkeypatch.setattr("career.notifications.telegram_send", lambda chat, text, job_id=None: telegram_sent.append(job_id))
    monkeypatch.setattr("career.notifications.email_send", lambda subject, text, to=None: emails.append((subject, text)))
    prefs = client.get("/api/state").json()["preferences"]
    client.put("/api/preferences", json={**prefs, "alerts_enabled": True, "notify_channels": ["telegram", "email"], "alert_mode": "each", "email_digest": True})
    client.post("/api/scan")
    assert len(telegram_sent) == 3 and all(telegram_sent)
    assert len(emails) == 1 and "3 new matching" in emails[0][0]
    assert "1. Climate Data Scientist" in emails[0][1] and "3. " in emails[0][1] and "Why you fit: fit" in emails[0][1]
    run = client.get("/api/state").json()["runs"][0]
    assert run["delivered"]["email"] == "accepted" and run["delivered"]["telegram"] == "accepted"
    client.post("/api/scan")
    assert len(emails) == 1 and len(telegram_sent) == 3


def test_review_link_only_on_public_dashboards(monkeypatch):
    from career.notifications import alert_text, digest_text

    job = {"title": "T", "company": "C", "location": "L", "url": "https://example.org/j", "deadline": None}
    match = {"score": 80, "summary": "s", "strengths": [], "gaps": []}
    monkeypatch.setattr(settings, "public_url", "http://localhost:8000")
    assert "localhost" not in alert_text(job, match, "id1") and "Posting: https://example.org/j" in alert_text(job, match, "id1")
    assert "localhost" not in digest_text([("id1", job, match)])
    monkeypatch.setattr(settings, "public_url", "https://career.example.org")
    assert "https://career.example.org/app/?job=id1" in alert_text(job, match, "id1")


def test_source_test_endpoint_and_toggle(client, monkeypatch):
    monkeypatch.setattr("career.main.collect", lambda source, seen, ctx: ([JOB, {"url": "x", "partial": True}], []))
    r = client.post("/api/sources/test", json={"kind": "greenhouse", "value": "example"}).json()
    assert r["received"] == 2 and r["sample"][0]["title"] == JOB["title"]
    assert client.post("/api/sources/test", json={"kind": "rss", "value": "not a url"}).status_code == 422
    src = client.post("/api/sources", json={"kind": "rss", "value": "https://example.org/feed.xml"}).json()
    assert client.put(f"/api/sources/{src['id']}", json={"enabled": False}).json()["enabled"] is False
    assert client.get("/api/state").json()["suggested_sources"]


def test_notify_test_endpoint(client, monkeypatch):
    assert client.post("/api/notify/test/telegram").status_code == 422
    monkeypatch.setattr("career.notifications.availability", lambda db=None: {"email": True})
    sent = []
    monkeypatch.setattr("career.notifications.email_send", lambda subject, text: sent.append(subject))
    assert client.post("/api/notify/test/email").json()["status"] == "accepted" and sent


def test_review_triggers_one_revision_before_accepting(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "fake")
    calls = []

    def structured(model, schema, instructions, data):
        calls.append(schema.__name__)
        if schema is Package:
            text = "Invented a new satellite." if "REVISION" not in instructions else "Used satellite data."
            return Package(cv={"title": "CV", "paragraphs": [{"text": text, "evidence_ids": ["F1"]}]}, cover_letter={"title": "L", "paragraphs": []}, answers=[], additional_documents=[], checklist=[], missing_information=[])
        first = calls.count("QualityReview") == 1
        return QualityReview(unsupported_claims=["Invented satellite."] if first else [], missing_requirements=["Passport copy"] if not first else [])

    monkeypatch.setattr("career.ai.structured", structured)
    result = write_package({"facts": [{"id": "F1", "text": "Used satellite data.", "verified": True}]}, {"title": "Scientist"}, {})
    assert calls == ["Package", "QualityReview", "Package", "QualityReview"]
    assert result["cv"]["paragraphs"][0]["text"] == "Used satellite data."
    assert result["missing_information"] == ["Passport copy"] and result["review_notes"]
