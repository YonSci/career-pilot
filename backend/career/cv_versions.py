"""CV versions: target roles over one body of verified evidence.

A member's verified facts stay the single source of truth. A CV version names a
target role and keeps, for it, a headline, the search keywords that find such
roles, and the facts to lead with. Searches screen with the keywords of every
version as well as the member's own; each job is matched to the version whose
keywords fit it best (the member can change it); an application drafted for the
job is written for that version's role. Matching itself always uses all
verified evidence, so a version never hides a qualification from the score."""

from .db import read, put
from .relevance import keyword_hits

MAX_VERSIONS = 5
KEY = "cv_versions"


def versions(db):
    return (read(db, KEY, {}) or {}).get("items", [])


def save(db, items, profile):
    """Store versions, keeping only facts that exist and are verified."""
    verified = {f["id"] for f in profile.get("facts", []) if f.get("verified")}
    clean = []
    for v in items[:MAX_VERSIONS]:
        clean.append({**v, "fact_ids": [i for i in v.get("fact_ids", []) if i in verified]})
    put(db, KEY, KEY, {"items": clean})
    return clean


def search_keywords(prefs, items):
    """The member's keywords plus every version's, without duplicates."""
    out, seen = [], set()
    for k in [*prefs.get("keywords", []), *(k for v in items for k in v.get("keywords", []))]:
        if k.strip() and k.strip().lower() not in seen:
            seen.add(k.strip().lower())
            out.append(k.strip())
    return out


def best_for(job, items):
    """The id of the version whose keywords fit the posting best (title counts
    three times), or None when no version's keywords appear in it."""
    best, top = None, 0
    for v in items:
        kws = v.get("keywords", [])
        if not kws:
            continue
        score = 3 * len(keyword_hits(job.get("title", ""), kws)) + len(keyword_hits(job.get("description", ""), kws))
        if score > top:
            best, top = v["id"], score
    return best


def for_job(job, items):
    """The version a job's application is written for: the member's choice, else the best fit."""
    chosen = job.get("cv_version")
    if chosen and any(v["id"] == chosen for v in items):
        return chosen
    return best_for(job, items)


def tailor(profile, version):
    """The profile as the drafting step sees it for this version: its headline,
    and its facts first. All verified facts stay available as evidence."""
    if not version:
        return profile
    lead = [i for i in version.get("fact_ids", [])]
    order = {fid: n for n, fid in enumerate(lead)}
    facts = sorted(profile.get("facts", []), key=lambda f: order.get(f.get("id"), len(order)))
    return {
        **profile,
        "headline": version.get("headline") or profile.get("headline", ""),
        "facts": facts,
        "focus": {"target_role": version["name"], "lead_with": lead},
    }
