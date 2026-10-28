"""Catalog phase 4: a few postings the keywords reject are evaluated anyway, to measure what keywords miss."""

from career import jev_report
from career.config import settings
from tests.test_jev import LLM_MATCH
from tests.test_workflow import JOB, verified_profile

CLEANER = {**JOB, "title": "Office cleaner", "url": "https://example.org/jobs/cleaner", "description": "Cleaning and tidying offices daily."}
DRIVER = {**JOB, "title": "Delivery driver", "url": "https://example.org/jobs/driver", "description": "Driving vans around the city."}


def scan(client, monkeypatch, budget=2):
    monkeypatch.setattr("career.service.collect", lambda *a, **k: ([JOB, CLEANER, DRIVER], []))
    monkeypatch.setattr(settings, "openai_api_key", "fake-test-key")
    monkeypatch.setattr(settings, "max_matches_per_run", budget)
    calls = []
    monkeypatch.setattr("career.service.match_job", lambda profile, job, prefs: calls.append(job["title"]) or LLM_MATCH)
    client.post("/api/scan")
    return calls


def test_one_rejected_posting_per_search_is_evaluated_reported_and_never_alerted(client, monkeypatch, capsys):
    verified_profile(client)
    client.post("/api/sources", json={"kind": "greenhouse", "value": "example"})
    prefs = client.get("/api/state").json()["preferences"]
    client.put("/api/preferences", json={**prefs, "alerts_enabled": True, "notify_channels": []})
    monkeypatch.setattr(settings, "keyword_sample_per_month", 1)
    calls = scan(client, monkeypatch)
    state = client.get("/api/state").json()
    samples = [j for j in state["jobs"] if j.get("keyword_sample")]
    assert len(samples) == 1 and samples[0]["title"] in (CLEANER["title"], DRIVER["title"])
    # Evaluated ahead of keyword order, within the same budget.
    assert sorted(calls) == sorted([JOB["title"], samples[0]["title"]]) and samples[0]["match"]["score"] == 90
    # Both score 90, but only the posting the keywords kept is alerted.
    assert state["runs"][0]["alerts"] == 1
    assert {a["job_id"] for a in state["alerts"]} == {next(j["id"] for j in state["jobs"] if j["title"] == JOB["title"])}

    jev_report.main([])
    out = capsys.readouterr().out
    assert "Keyword-rejected sample evaluated by the LLM: 1" in out
    assert "good matches (LLM >= 60): 1/1 (100%, 95% interval 21-100%); among postings the keywords kept: 1/1" in out

    # The month's quota is used: the other rejected posting is not stored.
    scan(client, monkeypatch)
    assert sum(1 for j in client.get("/api/state").json()["jobs"] if j.get("keyword_sample")) == 1


def test_keyword_sample_can_be_switched_off_and_needs_a_verified_cv(client, monkeypatch):
    monkeypatch.setattr(settings, "keyword_sample_per_month", 10)
    client.post("/api/sources", json={"kind": "greenhouse", "value": "example"})
    scan(client, monkeypatch)  # no verified CV: nothing would be evaluated, so nothing is sampled
    assert not any(j.get("keyword_sample") for j in client.get("/api/state").json()["jobs"])
    monkeypatch.setattr(settings, "openai_api_key", "")  # CV extraction uses the test stand-in
    verified_profile(client)
    monkeypatch.setattr(settings, "keyword_sample_per_month", 0)
    scan(client, monkeypatch)
    assert not any(j.get("keyword_sample") for j in client.get("/api/state").json()["jobs"])
