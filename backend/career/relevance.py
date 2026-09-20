"""Cheap lexical screening that decides which postings deserve an AI evaluation.

The previous filter required the exact keyword phrase, so "Data Scientist" never
matched the keyword "data science". This version compares word stems, so each
word of a keyword phrase must appear somewhere in the text in any inflection.
False positives only cost one bounded AI evaluation; false negatives lose a job.
"""

import re
from datetime import datetime, timezone

_SUFFIXES = (
    "ologies",
    "ically",
    "ations",
    "ology",
    "ation",
    "ical",
    "ings",
    "ists",
    "ions",
    "ment",
    "ing",
    "ist",
    "ion",
    "ive",
    "ity",
    "ies",
    "ial",
    "al",
    "ed",
    "es",
    "er",
    "s",
    "e",
)

AFRICAN_COUNTRIES = {
    "algeria", "angola", "benin", "botswana", "burkina faso", "burundi",
    "cabo verde", "cape verde", "cameroon", "central african republic", "chad",
    "comoros", "congo", "côte d'ivoire", "cote d'ivoire", "ivory coast",
    "djibouti", "egypt", "equatorial guinea", "eritrea", "eswatini", "ethiopia",
    "gabon", "gambia", "ghana", "guinea", "guinea-bissau", "kenya", "lesotho",
    "liberia", "libya", "madagascar", "malawi", "mali", "mauritania",
    "mauritius", "morocco", "mozambique", "namibia", "niger", "nigeria",
    "rwanda", "sao tome", "senegal", "seychelles", "sierra leone", "somalia",
    "south africa", "south sudan", "sudan", "tanzania", "togo", "tunisia",
    "uganda", "zambia", "zimbabwe", "sahel", "east africa", "west africa",
    "southern africa", "horn of africa", "nairobi", "addis ababa", "kampala",
    "dakar", "accra", "lagos", "abuja", "kigali", "dar es salaam", "lusaka",
}

REMOTE_WORDS = ("remote", "home-based", "home based", "anywhere", "worldwide", "global", "telecommute", "work from home")


def stem(word: str) -> str:
    word = word.lower()
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9][a-z0-9+#.]*", (text or "").lower())


def _key(token: str) -> str:
    """Comparison key: exact short words, otherwise a 5-character stem prefix so
    inflections agree (science / scientist / scientific)."""
    key = stem(token)
    return key if len(key) < 4 else key[:5]


def _matches(key: str, word: str) -> bool:
    return word == key if len(key) < 4 else word.startswith(key)


def phrase_matches(phrase: str, text_words: list[str]) -> bool:
    """A multi-word keyword must appear as a phrase: all of its words inside a
    short window (any order), so "agricultural digitalisation" satisfies
    "digital agriculture" but a stray "remote" and "sensitive" do not satisfy
    "remote sensing"."""
    tokens = words(phrase)
    if not tokens:
        return False
    keys = [_key(t) for t in tokens]
    if len(keys) == 1:
        return any(_matches(keys[0], w) for w in text_words)
    span = len(keys) + 1
    for i, word in enumerate(text_words):
        if not any(_matches(k, word) for k in keys):
            continue
        window = text_words[i : i + span]
        if all(any(_matches(k, w) for w in window) for k in keys):
            return True
    return False


def keyword_hits(text: str, keywords: list[str]) -> list[str]:
    text_words = words(text)
    return [k for k in keywords if phrase_matches(k, text_words)]


def excluded(text: str, excluded_keywords: list[str]) -> bool:
    lowered = (text or "").lower()
    return any(t and t.lower() in lowered for t in excluded_keywords)


def location_match(job_location: str, preferred: list[str]) -> bool:
    """True when the job location satisfies any preferred location."""
    if not preferred:
        return True
    loc = (job_location or "").lower()
    if not loc or loc in ("not specified", "unspecified", "n/a"):
        # Unknown locations are kept: many consultancies omit them.
        return True
    for pref in preferred:
        p = pref.strip().lower()
        if not p:
            continue
        if p == "remote" and any(w in loc for w in REMOTE_WORDS):
            return True
        if p == "africa" and (
            "africa" in loc or any(c in loc for c in AFRICAN_COUNTRIES)
        ):
            return True
        if p in loc:
            return True
    return False


def screen(job: dict, prefs: dict) -> dict:
    """Return screening details for a posting. `keep` decides ingestion."""
    text = f"{job.get('title', '')}\n{job.get('description', '')}"
    if excluded(text, prefs.get("excluded_keywords", [])):
        return {"keep": False, "reason": "excluded keyword"}
    keywords = [k for k in prefs.get("keywords", []) if k.strip()]
    hits = keyword_hits(text, keywords) if keywords else []
    if keywords and not hits:
        return {"keep": False, "reason": "no keyword match"}
    title_hits = keyword_hits(job.get("title", ""), keywords) if keywords else []
    loc_ok = location_match(job.get("location", ""), prefs.get("locations", []))
    if prefs.get("location_mode") == "strict" and not loc_ok:
        return {"keep": False, "reason": "location outside preferences"}
    return {
        "keep": True,
        "keyword_hits": hits,
        "title_hits": title_hits,
        "location_match": loc_ok,
    }


def priority(job: dict) -> tuple:
    """Sort key: title matches and preferred locations first, then newest."""
    s = job.get("screen") or {}
    when = job.get("posted") or job.get("created") or ""
    try:
        ts = datetime.fromisoformat(str(when).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
    except ValueError:
        ts = datetime.fromtimestamp(0, timezone.utc)
    return (
        -len(s.get("title_hits", [])),
        0 if s.get("location_match", True) else 1,
        -ts.timestamp(),
    )
