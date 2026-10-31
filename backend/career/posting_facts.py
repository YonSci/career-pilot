"""Posting details the job list filters on, and where the posting is, for the map.

What the AI evaluation recorded from the posting comes first; postings not yet
evaluated (or evaluated before details were recorded) fall back to what their
text states, read by the same rules as the public job pages. A detail the
posting does not state stays None: filters treat it as unknown, never as a no.
"""

import re
from .geo import is_remote, place
from .public_jobs import extract_details

NOT_STATED = {"", "not stated", "not specified", "none", "n/a", "unknown"}
SENIORITY = [
    ("Leadership", r"\b(director|head of|chief|vice president|vp|principal|team lead(er)?|lead)\b|\bD-?[12]\b|\bP-?5\b"),
    ("Senior", r"\b(senior|sr\.?|expert)\b|\bP-?4\b"),
    ("Mid-level", r"\b(mid[- ]?level|intermediate|mid[- ]senior)\b|\bP-?3\b"),
    ("Entry", r"\b(intern(ship)?|junior|jr\.?|trainee|graduate|entry[- ]level|assistant)\b|\bP-?[12]\b"),
]
CONTRACTS = [
    ("Internship", r"\bintern(ship)?\b"),
    ("Volunteer", r"\bvolunteer\b"),
    ("Consultancy", r"\bconsultan(t|cy)\b|\bcall for proposals\b|\bexpression of interest\b"),
    ("Fellowship", r"\bfellow(ship)?\b"),
    ("Part-time", r"\bpart[- ]time\b"),
    ("Fixed-term", r"\bfixed[- ]term\b|\btemporary\b|\b\d{1,2}[- ]months?\b"),
    ("Full-time", r"\bfull[- ]time\b|\bpermanent\b"),
]


def stated(value):
    value = str(value or "").strip()
    return value if value.lower().rstrip(".") not in NOT_STATED else None


def first(rules, *texts):
    for text in texts:
        for label, pattern in rules:
            if text and re.search(pattern, text, re.I):
                return label
    return None


def work_label(text):
    low = str(text or "").lower()
    if "hybrid" in low:
        return "Hybrid"
    if re.search(r"\bremote\b|home[- ]based|work from home|telecommut", low):
        return "Remote"
    if re.search(r"\bon[- ]?site\b|\bin[- ]person\b|\boffice[- ]based\b|\bin the office\b", low):
        return "On-site"
    return None


def facts(job):
    details = (job.get("match") or {}).get("details") or {}
    title, location = job.get("title") or "", job.get("location") or ""
    salary, contract, work = extract_details(title, job.get("description"), location)
    ai_seniority = stated(details.get("seniority"))
    ai_salary = stated(details.get("salary"))
    where = place(location, title)
    return {
        "work": work_label(stated(details.get("work_arrangement"))) or work or ("Remote" if is_remote(location) else None),
        # The title says the level more reliably than a description that mentions several.
        "seniority": first(SENIORITY, ai_seniority, title),
        "contract": first(CONTRACTS, title, stated(details.get("contract_duration"))) or contract,
        "salary": ai_salary or salary,
        "country": where["country"] if where else None,
        "lat": where["lat"] if where else None,
        "lng": where["lng"] if where else None,
    }


_cache = {}


def cached(key, job):
    """facts(job), remembered per (job id, last update): the job list asks for every job."""
    if key not in _cache:
        if len(_cache) > 50000:
            _cache.clear()
        _cache[key] = facts(job)
    return _cache[key]
