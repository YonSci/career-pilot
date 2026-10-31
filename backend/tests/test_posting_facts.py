"""Posting details for the job-list filters and the map."""

from career.geo import place
from career.posting_facts import facts
from tests.test_workflow import JOB


def test_locations_resolve_to_the_country_they_name():
    cases = {
        "Addis Ababa, Ethiopia": "Ethiopia",
        "Juba, South Sudan": "South Sudan",
        "Khartoum": "Sudan",
        "Bissau, Guinea-Bissau": "Guinea-Bissau",
        "Conakry": "Guinea",
        "Goma": "Democratic Republic of the Congo",
        "Niamey, Niger": "Niger",
        "Abuja, Nigeria": "Nigeria",
        "Sydney, New South Wales, Australia": "Australia",
        "Nairobi, Kenya; Kampala, Uganda": "Kenya",
    }
    for location, country in cases.items():
        assert place(location)["country"] == country, location
    for location in ("Remote", "Not specified", "USD 4,000", "us", ""):
        assert place(location) is None, location
    # The title is the fallback when the location does not say.
    assert place("Not specified", "Hydrologist - Somalia")["country"] == "Somalia"


def test_details_come_from_the_evaluation_first_then_the_posting_text():
    unevaluated = facts({"title": "Senior Hydrologist (P4) - Consultancy", "location": "Remote", "description": "Daily rate USD 500 per day for 6 months."})
    assert unevaluated == {"work": "Remote", "seniority": "Senior", "contract": "Consultancy", "salary": "USD 500 per day", "country": None, "lat": None, "lng": None}
    evaluated = facts({
        "title": "GIS Analyst", "location": "Addis Ababa", "description": "Office work.",
        "match": {"details": {"seniority": "Mid-level", "work_arrangement": "Hybrid, three days in the office", "salary": "not stated", "contract_duration": "12 months"}},
    })
    assert (evaluated["work"], evaluated["seniority"], evaluated["contract"], evaluated["salary"], evaluated["country"]) == ("Hybrid", "Mid-level", "Fixed-term", None, "Ethiopia")
    # Nothing stated stays unknown rather than guessed.
    assert facts({"title": "Data Scientist", "location": "", "description": "Join us."})["seniority"] is None


def test_the_job_list_carries_the_details(client):
    client.post("/api/jobs", json={**JOB, "title": "Junior GIS Officer", "location": "Nairobi", "url": "https://example.org/jobs/gis-1"})
    job = next(j for j in client.get("/api/state").json()["jobs"] if j["url"] == "https://example.org/jobs/gis-1")
    assert job["facts"]["seniority"] == "Entry" and job["facts"]["country"] == "Kenya" and job["facts"]["lat"] is not None
