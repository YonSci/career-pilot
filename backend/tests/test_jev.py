from types import SimpleNamespace
from career import jev
from career.config import settings
from career.jev import jev_key, jev_state, score_job
from tests.conftest import OWNER
from tests.test_workflow import JOB, verified_profile

SENIOR = {**JOB, "title": "Senior Data Scientist, climate machine learning", "url": "https://example.org/jobs/2", "description": "Lead machine learning for climate services in Ethiopia with Python. " * 2}
GIS = {**JOB, "title": "GIS Lead", "url": "https://example.org/jobs/3", "description": "Geospatial climate data science and remote sensing in Ethiopia with Python."}
FEED = [SENIOR, JOB, GIS]
LLM_MATCH = {"score": 90, "summary": "Strong", "requirements": [], "strengths": [], "gaps": [], "mode": "ai"}


def fake_scores(by_title, calls):
    """score_job stand-in: a fixed (score, confidence) per title, with the real cache key."""
    def score(profile, job, prefs):
        calls.append(job["title"])
        value, confidence = by_title[job["title"]]
        return {"score": value, "confidence": confidence, "dimensions": {}, "model": "jev-test", "rubric": "1",
                "key": jev_key(jev_state(profile, job, prefs)), "tokens": 100, "scored": "now"}
    return score


def search_with(client, monkeypatch, mode, by_title, budget=1):
    verified_profile(client)
    client.post("/api/sources", json={"kind": "greenhouse", "value": "example"})
    monkeypatch.setattr("career.service.collect", lambda *a, **k: (FEED, []))
    monkeypatch.setattr(settings, "openai_api_key", "fake-test-key")
    monkeypatch.setattr(settings, "typesafe_api_key", "fake-jev-key")
    monkeypatch.setattr(settings, "jev_mode", mode)
    monkeypatch.setattr(settings, "max_matches_per_run", budget)
    jev_calls, llm_calls = [], []
    monkeypatch.setattr("career.service.score_job", fake_scores(by_title, jev_calls))
    monkeypatch.setattr("career.service.match_job", lambda profile, job, prefs: llm_calls.append(job["title"]) or LLM_MATCH)
    client.post("/api/scan")
    return jev_calls, llm_calls


def test_score_job_combines_weighted_dimensions_and_sends_no_contact_details(monkeypatch):
    sent = {}
    levels = {"experience": 3, "skills": 2, "domain": 0, "seniority": 0, "location": 0, "preferences": 0}

    def system_one(state, questions):
        sent["state"], sent["questions"] = state, questions
        return SimpleNamespace(
            scores={n: SimpleNamespace(score=levels[n], confidence=0.8) for n in questions},
            model="jev-2026-10",
            usage=SimpleNamespace(input_tokens=1234),
        )

    monkeypatch.setattr(jev, "client", lambda: SimpleNamespace(system_one=system_one))
    profile = {"facts": [
        {"id": "F1", "category": "Role", "text": "Built Python climate pipelines.", "verified": True},
        {"id": "F2", "category": "Contact", "text": "applicant@example.org", "verified": True},
        {"id": "F3", "category": "Skill", "text": "Unverified claim.", "verified": False},
    ]}
    result = score_job(profile, JOB, {"keywords": ["climate"], "locations": ["Remote"], "contract_types": [], "min_score": 70})
    # 100 * (0.30 * 3/3 + 0.25 * 2/3) = 46.7
    assert result["score"] == 47 and result["confidence"] == 0.8 and result["tokens"] == 1234
    assert result["model"] == "jev-2026-10" and result["key"] == jev_key(sent["state"])
    assert [f["id"] for f in sent["state"]["verified_facts"]] == ["F1"]
    assert "url" not in sent["state"]["job"] and "min_score" not in sent["state"]["preferences"]
    assert set(sent["questions"]) == set(jev.WEIGHTS)


def test_score_job_through_the_real_sdk_client(monkeypatch):
    """The SDK builds the request and parses the response; only the network is faked."""
    import json
    import httpx2
    from typesafe_sdk import TypeSafeClient

    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        answers = {
            name: {"type": "score", "score": 1.5, "confidence": 0.7,
                   "legend": {str(i): c for i, c in enumerate(q["criteria"])},
                   "probabilities": {"0": 0.1, "1": 0.4, "2": 0.4, "3": 0.1}}
            for name, q in seen["body"]["questions"].items()
        }
        return httpx2.Response(200, json={"model": "jev-2026-10", "usage": {"input_tokens": 900, "output_tokens": 6}, "answers": answers})

    sdk = TypeSafeClient(api_key="test-key", transport=httpx2.MockTransport(handler), compression=False)
    monkeypatch.setattr(jev, "client", lambda: sdk)
    profile = {"facts": [{"id": "F1", "category": "Role", "text": "Built Python climate pipelines.", "verified": True}]}
    result = score_job(profile, JOB, {"keywords": ["climate"], "locations": ["Remote"], "contract_types": []})
    assert seen["path"] == "/v1/systemone" and seen["body"]["model"] == "jev-latest"
    assert all(q["type"] == "score" and len(q["criteria"]) == 4 for q in seen["body"]["questions"].values())
    assert result["score"] == 50 and result["confidence"] == 0.7 and result["tokens"] == 900
    assert result["dimensions"]["skills"] == {"score": 0.5, "confidence": 0.7}


def test_score_job_requires_verified_evidence(monkeypatch):
    monkeypatch.setattr(jev, "client", lambda: (_ for _ in ()).throw(AssertionError("no call expected")))
    try:
        score_job({"facts": []}, JOB, {})
    except ValueError as e:
        assert "Verified" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_shadow_mode_stores_scores_without_changing_llm_order(client, monkeypatch):
    jev_calls, llm_calls = search_with(client, monkeypatch, "shadow", {SENIOR["title"]: (10, 0.9), JOB["title"]: (80, 0.9), GIS["title"]: (50, 0.9)})
    assert sorted(jev_calls) == sorted(j["title"] for j in FEED)
    assert llm_calls == [SENIOR["title"]]  # keyword priority, as without JEV
    state = client.get("/api/state").json()
    assert all(j["jev"]["score"] for j in state["jobs"])
    assert state["runs"][0]["jev"] == {"scored": 3, "cached": 0, "failed": 0, "held": 0, "tokens": 300}


def test_rank_mode_sends_jev_shortlist_to_llm_and_caches_scores(client, monkeypatch):
    # Senior leads on keywords but JEV is confident it is weak; GIS is low but uncertain.
    scores = {SENIOR["title"]: (10, 0.9), JOB["title"]: (80, 0.9), GIS["title"]: (20, 0.3)}
    jev_calls, llm_calls = search_with(client, monkeypatch, "rank", scores)
    assert llm_calls == [JOB["title"]]
    run = client.get("/api/state").json()["runs"][0]
    assert run["jev"]["held"] == 1 and run["matched"] == 1
    assert any("1 postings await evaluation" in w for w in run["warnings"])  # GIS waits; Senior is held, not queued
    client.post("/api/scan")
    assert len(jev_calls) == 3  # unchanged postings are not scored again
    assert llm_calls == [JOB["title"], GIS["title"]]
    assert client.get("/api/state").json()["runs"][0]["jev"]["cached"] == 2


def test_report_compares_jev_with_llm_and_decisions(client, monkeypatch, capsys):
    from career import jev_report

    scores = {SENIOR["title"]: (10, 0.9), JOB["title"]: (80, 0.9), GIS["title"]: (20, 0.3)}
    search_with(client, monkeypatch, "shadow", scores, budget=3)
    jobs = {j["title"]: j["id"] for j in client.get("/api/state").json()["jobs"]}
    assert client.put(f"/api/jobs/{jobs[SENIOR['title']]}/decision", json={"status": "saved"}).status_code == 200
    jev_report.main()
    out = capsys.readouterr().out
    assert "Rank mode would send to the LLM: 2/3 (67%)" in out
    assert "LLM-strong matches (>= each member's minimum score) kept: 2/3 (67%)" in out
    assert "Saved or applied postings kept: 0/1 (0%)" in out
    # Senior (10, confident) is dropped at every cutoff; GIS (20, uncertain) is always kept.
    assert "  JEV_MIN_SCORE=20: sends 2/3 (67%), keeps 2/3 (67%) good matches\n" in out
    assert "  JEV_MIN_SCORE=40: sends 2/3 (67%), keeps 2/3 (67%) good matches (current)" in out
    assert jev_report.spearman([1, 2, 3], [10, 20, 30]) == 1.0


def test_jev_outage_falls_back_to_keyword_order(client, monkeypatch):
    def down(*a):
        raise RuntimeError("JEV unavailable")

    verified_profile(client)
    client.post("/api/sources", json={"kind": "greenhouse", "value": "example"})
    monkeypatch.setattr("career.service.collect", lambda *a, **k: (FEED, []))
    monkeypatch.setattr(settings, "openai_api_key", "fake-test-key")
    monkeypatch.setattr(settings, "typesafe_api_key", "fake-jev-key")
    monkeypatch.setattr(settings, "jev_mode", "rank")
    monkeypatch.setattr(settings, "max_matches_per_run", 1)
    monkeypatch.setattr("career.service.score_job", down)
    llm_calls = []
    monkeypatch.setattr("career.service.match_job", lambda profile, job, prefs: llm_calls.append(job["title"]) or LLM_MATCH)
    client.post("/api/scan")
    run = client.get("/api/state").json()["runs"][0]
    assert run["status"] == "completed" and run["jev"]["failed"] >= 1
    assert llm_calls == [SENIOR["title"]]


def test_jev_only_for_listed_accounts_and_with_a_key(client, monkeypatch):
    monkeypatch.setattr(settings, "jev_accounts", "someone-else@example.org")
    jev_calls, llm_calls = search_with(client, monkeypatch, "rank", {})
    assert jev_calls == [] and llm_calls == [SENIOR["title"]]
    assert "jev" not in client.get("/api/state").json()["runs"][0]
    monkeypatch.setattr(settings, "jev_accounts", OWNER["email"].upper())
    monkeypatch.setattr(settings, "typesafe_api_key", "")
    client.post("/api/scan")
    assert jev_calls == []
