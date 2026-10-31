"""CV versions: target roles that widen the search, fit jobs, and focus application drafts."""

from career.config import settings
from career.schemas import RoleSuggestion, SuggestedRole, SuggestedTerm
from tests.test_workflow import JOB, verified_profile, package

HYDRO = {**JOB, "title": "Flood Hydrologist", "url": "https://example.org/jobs/hydro", "description": "Model river floods and run early warning systems for the basin authority."}


def version(id, name, keywords, fact_ids=(), headline=""):
    return {"id": id, "name": name, "headline": headline, "keywords": keywords, "fact_ids": list(fact_ids)}


def test_versions_keep_only_verified_facts_and_are_limited(client):
    facts = [f["id"] for f in verified_profile(client)["facts"]]
    saved = client.put("/api/cv-versions", json={"items": [version("a", "Hydrologist", ["hydrology", " "], [facts[0], "F999"])]}).json()["items"]
    assert saved == [version("a", "Hydrologist", ["hydrology"], [facts[0]])]
    assert client.get("/api/state").json()["cv_versions"] == saved
    assert client.put("/api/cv-versions", json={"items": [version("a", "One", []), version("a", "Two", [])]}).status_code == 422
    assert client.put("/api/cv-versions", json={"items": [version(str(i), f"Role {i}", []) for i in range(6)]}).status_code == 422


def test_version_keywords_find_jobs_and_each_job_gets_the_best_fit(client, monkeypatch):
    verified_profile(client)
    # The member's own keywords would discard the hydrology posting.
    prefs = client.get("/api/state").json()["preferences"]
    assert client.put("/api/preferences", json={**prefs, "keywords": ["data science"]}).status_code == 200
    client.put("/api/cv-versions", json={"items": [version("d", "Data scientist", ["data science"]), version("h", "Hydrologist", ["hydrologist", "flood"])]})
    monkeypatch.setattr("career.service.collect", lambda *a, **k: ([JOB, HYDRO], []))
    client.post("/api/sources", json={"kind": "greenhouse", "value": "example"})
    client.post("/api/scan")
    jobs = {j["title"]: j for j in client.get("/api/state").json()["jobs"]}
    assert jobs["Flood Hydrologist"]["cv_version_id"] == "h" and jobs[JOB["title"]]["cv_version_id"] == "d"

    # The member can choose another version for a job, and return to the best fit.
    hydro = jobs["Flood Hydrologist"]["id"]
    assert client.put(f"/api/jobs/{hydro}/cv-version", json={"cv_version": "d"}).json()["cv_version_id"] == "d"
    assert client.get(f"/api/jobs/{hydro}").json()["cv_version_id"] == "d"
    assert client.put(f"/api/jobs/{hydro}/cv-version", json={"cv_version": "nope"}).status_code == 422
    assert client.put(f"/api/jobs/{hydro}/cv-version", json={"cv_version": None}).json()["cv_version_id"] == "h"


def test_application_is_written_for_the_jobs_version(client, monkeypatch):
    facts = [f["id"] for f in verified_profile(client)["facts"]]
    lead = facts[-1]
    client.put("/api/cv-versions", json={"items": [version("c", "Climate data scientist", ["climate"], [lead], "Climate data scientist building Python pipelines")]})
    j = client.post("/api/jobs", json=JOB).json()
    monkeypatch.setattr(settings, "openai_api_key", "fake-test-key")
    seen = {}

    def write(profile, job, match):
        seen.update(profile)
        return package()

    monkeypatch.setattr("career.service.write_package", write)
    assert client.post(f"/api/jobs/{j['id']}/prepare").status_code == 200
    assert seen["focus"] == {"target_role": "Climate data scientist", "lead_with": [lead]}
    assert seen["headline"] == "Climate data scientist building Python pipelines"
    # The lead fact comes first; every verified fact is still available as evidence.
    assert seen["facts"][0]["id"] == lead and {f["id"] for f in seen["facts"]} == set(facts)
    application = client.get("/api/state").json()["applications"][0]
    assert application["cv_version"] == "Climate data scientist"
    # The stored profile itself is unchanged.
    assert "focus" not in client.get("/api/state").json()["profile"]


def test_suggested_roles_cite_real_evidence(client, monkeypatch):
    facts = [f["id"] for f in verified_profile(client)["facts"]]
    monkeypatch.setattr(settings, "openai_api_key", "fake-test-key")
    output = RoleSuggestion(
        roles=[
            SuggestedRole(name="Hydrologist", headline="Hydrologist", keywords=[SuggestedTerm(term="hydrology", evidence_ids=[facts[0]]), SuggestedTerm(term="astrophysics", evidence_ids=["F999"])], evidence_ids=[facts[0], "F999"]),
            SuggestedRole(name="Astronaut", headline="Astronaut", keywords=[SuggestedTerm(term="space", evidence_ids=["F999"])], evidence_ids=["F999"]),
        ]
    )
    monkeypatch.setattr("career.ai.structured", lambda *a, **k: output)
    roles = client.post("/api/cv-versions/suggest").json()["roles"]
    # Unsupported keywords and facts are dropped; a role with no real evidence is not offered.
    assert roles == [{"name": "Hydrologist", "headline": "Hydrologist", "keywords": ["hydrology"], "fact_ids": [facts[0]]}]
