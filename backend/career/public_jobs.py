"""Public job listings for the landing page.

Only postings that came from public boards and feeds are shown, with public
facts only (title, employer, location, source, dates, link, short excerpt).
Nothing about who collected a posting, how it scored for anyone, or what
anyone did with it is exposed. Postings from mailboxes and manual entries
are never listed. Results are cached for ten minutes."""

import html
import json
import time
from datetime import datetime, timezone, timedelta
from .db import Record
from .service import expired

PRIVATE_SOURCES = ("Email alert", "Manual")
FEATURED_SCORE = 75
RELEVANT_SCORE = 60  # or a field keyword in the title: keeps generic postings off the public list
STALE_DAYS = 21
CLOSING_DAYS = 14
_cache = {"at": 0.0, "value": None}


def _parse(stamp):
    try:
        d = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _public(job, posted):
    description = " ".join((job.get("description") or "").split())
    return {
        "title": job.get("title") or "",
        "company": job.get("company") or "",
        "location": job.get("location") or "Not specified",
        "source": job.get("source") or "",
        "posted": posted.date().isoformat() if posted else None,
        "deadline": (job.get("deadline") or None),
        "url": job.get("url") or "",
        "excerpt": description[:220] + ("…" if len(description) > 220 else ""),
    }


def compute(db):
    now = datetime.now(timezone.utc)
    stale = now - timedelta(days=STALE_DAYS)
    seen = {}
    for row in db.query(Record).filter_by(kind="job").all():
        job = row.data
        source = job.get("source") or "Manual"
        if source in PRIVATE_SOURCES or not job.get("url") or job.get("status") == "archived" or expired(job):
            continue
        last_seen = _parse(job.get("last_seen")) or _parse(job.get("created"))
        if not last_seen or last_seen < stale:
            continue
        score = (job.get("match") or {}).get("score") or 0
        if not (job.get("screen") or {}).get("title_hits") and score < RELEVANT_SCORE:
            continue
        posted = _parse(job.get("posted")) or _parse(job.get("created"))
        key = job["url"].lower().rstrip("/")
        entry = seen.setdefault(key, {"job": _public(job, posted), "posted": posted or last_seen, "interest": 0, "created": _parse(job.get("created")) or last_seen})
        if score >= FEATURED_SCORE:
            entry["interest"] += 1
        if posted and posted > entry["posted"]:
            entry["posted"] = posted
    entries = list(seen.values())
    latest = sorted(entries, key=lambda e: e["posted"], reverse=True)
    featured = sorted((e for e in entries if e["interest"]), key=lambda e: (e["interest"], e["posted"]), reverse=True)
    horizon = (now + timedelta(days=CLOSING_DAYS)).date().isoformat()
    closing = sorted((e for e in entries if e["job"]["deadline"] and e["job"]["deadline"][:10] <= horizon), key=lambda e: e["job"]["deadline"])
    week = now - timedelta(days=7)
    return {
        "updated": now.isoformat(),
        "total": len(entries),
        "listed_last_7_days": sum(1 for e in entries if e["created"] >= week),
        "latest": [e["job"] for e in latest[:12]],
        "featured": [e["job"] for e in featured[:6]],
        "closing_soon": [e["job"] for e in closing[:8]],
    }


def listings(db, max_age=600):
    if _cache["value"] and time.time() - _cache["at"] < max_age:
        return _cache["value"]
    value = compute(db)
    _cache.update(at=time.time(), value=value)
    return value


def reset_cache():
    _cache.update(at=0.0, value=None)


# --- server-side rendering for the landing page ---------------------------------


def _days_left(deadline):
    d = _parse(deadline[:10] + "T23:59:59+00:00") if deadline else None
    return (d - datetime.now(timezone.utc)).days if d else None


def render_cards(jobs):
    """HTML for job cards; the same markup the landing page's script produces."""
    if not jobs:
        return '<p class="jobs-empty">Postings appear here as the beta collects them.</p>'
    out = []
    for j in jobs:
        left = _days_left(j.get("deadline"))
        badge = ""
        if left is not None:
            badge = f'<span class="job-badge {"urgent" if left <= 5 else ""}">Closes {"today" if left <= 0 else "in " + str(left) + " day" + ("" if left == 1 else "s")}</span>'
        posted = _parse(j.get("posted"))
        fresh = posted and (datetime.now(timezone.utc) - posted).days <= 3
        meta = " · ".join(x for x in (html.escape(j.get("source") or ""), ("Posted " + posted.strftime("%d %b")) if posted else "") if x)
        new_badge = '<span class="job-badge new">New</span>' if fresh else ""
        sep = " · " if j["company"] and j["location"] else ""
        out.append(
            '<article class="job-item">'
            f'<a class="job-link" href="{html.escape(j["url"])}" target="_blank" rel="noopener nofollow" data-title="{html.escape(j["title"])}">{html.escape(j["title"])}</a>'
            f'<p class="job-org">{html.escape(j["company"])}{sep}{html.escape(j["location"])}</p>'
            f'<p class="job-meta">{meta}{new_badge}{badge}</p>'
            "</article>"
        )
    return "".join(out)


def json_ld(jobs, site):
    """Schema.org ItemList of JobPosting entries for search engines."""
    items = []
    for i, j in enumerate(jobs, 1):
        posting = {
            "@type": "JobPosting",
            "title": j["title"],
            "description": j["excerpt"] or j["title"],
            "datePosted": j["posted"] or datetime.now(timezone.utc).date().isoformat(),
            "hiringOrganization": {"@type": "Organization", "name": j["company"] or "See posting"},
            "jobLocation": {"@type": "Place", "address": {"@type": "PostalAddress", "addressLocality": j["location"]}},
            "url": j["url"],
        }
        if j.get("deadline"):
            posting["validThrough"] = j["deadline"][:10]
        items.append({"@type": "ListItem", "position": i, "item": posting})
    data = {"@context": "https://schema.org", "@type": "ItemList", "name": "Latest jobs on Jobs Find AI", "url": site, "itemListElement": items}
    return '<script type="application/ld+json">' + json.dumps(data, ensure_ascii=False).replace("</", "<\\/") + "</script>"
