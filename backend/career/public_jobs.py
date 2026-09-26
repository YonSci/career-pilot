"""Public job listings for the landing page.

Only postings that came from public boards and feeds are shown, with public
facts only (title, employer, location, source, dates, link, short excerpt).
Nothing about who collected a posting, how it scored for anyone, or what
anyone did with it is exposed. Postings from mailboxes and manual entries
are never listed. Results are cached for ten minutes."""

import hashlib
import html
import json
import re
import time
from datetime import datetime, timezone, timedelta
from .db import Record
from .service import expired
from .config import settings

SECTORS = {
    "data-science": ("Data science, analytics and AI jobs", ["data", "analytics", "analyst", "machine learning", "ai", "statistic", "python", "engineer", "developer", "digital"]),
    "climate": ("Climate, hydrology and water jobs", ["climate", "hydrolog", "water", "wash", "weather", "meteorolog", "flood", "drought", "early warning", "resilience", "environment"]),
    "gis-remote-sensing": ("GIS and remote sensing jobs", ["gis", "geospatial", "remote sensing", "earth observation", "mapping", "spatial", "cartograph", "geograph"]),
    "agriculture": ("Agriculture and food systems jobs", ["agri", "food", "livestock", "crop", "agronom", "farm", "nutrition", "value chain"]),
    "mel": ("MEL, research and evaluation jobs", ["mel", "meal", "monitoring", "evaluation", "research", "learning", "assessment", "survey"]),
    "development": ("Development and humanitarian jobs", ["programme", "program", "humanitarian", "development", "consult", "officer", "coordinator", "manager", "director", "advisor"]),
}


AFRICA = ("ethiopia", "addis", "kenya", "nairobi", "uganda", "tanzania", "rwanda", "somalia", "sudan", "south sudan", "djibouti", "eritrea", "nigeria", "ghana", "senegal", "mali", "niger", "chad", "cameroon", "congo", "malawi", "zambia", "zimbabwe", "mozambique", "madagascar", "south africa", "botswana", "namibia", "angola", "burkina", "benin", "togo", "liberia", "sierra leone", "guinea", "gambia", "ivoire", "ivory coast", "egypt", "morocco", "tunisia", "algeria", "libya", "burundi", "central african", "africa", "sahel", "lesotho", "eswatini", "mauritania", "gabon", "seychelles", "mauritius", "comoros", "cabo verde", "cape verde", "sao tome", "equatorial guinea")


def slugify(text):
    s = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")
    return s[:60].rstrip("-") or "role"


def job_slug(title, url):
    return slugify(title) + "-" + hashlib.sha1((url or title).encode()).hexdigest()[:6]


def location_class(location):
    t = str(location or "").lower()
    if "remote" in t or "home-based" in t or "home based" in t:
        return "remote"
    if "ethiopia" in t or "addis" in t:
        return "ethiopia"
    if any(c in t for c in AFRICA):
        return "africa"
    return "other" if t and t != "not specified" else "other"


_SALARY = re.compile(r"(?:(?:USD|US\$|\$|EUR|€|GBP|£|ETB|Birr|KES|CHF)\s?[0-9][0-9,\.]{2,}(?:\s?(?:-|to|–)\s?(?:USD|US\$|\$|ETB|Birr)?\s?[0-9][0-9,\.]{2,})?(?:\s?(?:per|/|a)\s?(?:month|year|annum|day|hour))?|[0-9][0-9,\.]{2,}\s?(?:USD|ETB|Birr|EUR|GBP|KES)(?:\s?(?:per|/|a)\s?(?:month|year|annum|day|hour))?)", re.I)
_CONTRACT = [
    ("Internship", r"\bintern(ship)?\b"),
    ("Volunteer", r"\bvolunteer\b"),
    ("Consultancy", r"\bconsultan(t|cy)\b|\bcall for proposals\b|\bexpression of interest\b"),
    ("Fellowship", r"\bfellow(ship)?\b"),
    ("Part-time", r"\bpart[- ]time\b"),
    ("Fixed-term", r"\bfixed[- ]term\b|\b(\d{1,2})[- ]months?\b(?! ago)"),
    ("Full-time", r"\bfull[- ]time\b|\bpermanent\b"),
]


def extract_details(title, description, location=""):
    """Salary, contract type and work arrangement when the posting states them."""
    text = " ".join(str(description or "").split())
    head = (str(title or "") + " " + str(location or "") + " " + text[:4000])
    salary = None
    m = _SALARY.search(text)
    if m:
        salary = " ".join(m.group(0).split())[:60]
    contract = next((label for label, pat in _CONTRACT if re.search(pat, head, re.I)), None)
    work = None
    low = head.lower()
    if "hybrid" in low:
        work = "Hybrid"
    elif re.search(r"\bremote\b|home[- ]based|work from home", low):
        work = "Remote"
    elif re.search(r"\bon[- ]site\b|\bin[- ]person\b", low):
        work = "On-site"
    return salary, contract, work


def ago(stamp):
    d = _parse(stamp)
    if not d:
        return ""
    delta = datetime.now(timezone.utc) - d
    if delta.days <= 0:
        hours = max(1, int(delta.total_seconds() // 3600))
        return f"{hours}h ago" if hours < 24 else "1 day ago"
    if delta.days == 1:
        return "1 day ago"
    if delta.days < 30:
        return f"{delta.days} days ago"
    return d.strftime("%d %b")


def sector_of(title):
    t = " " + " ".join(str(title or "").lower().replace("/", " ").replace("-", " ").replace(",", " ").split()) + " "
    hits = []
    for slug, (_, words) in SECTORS.items():
        if any((" " + w + " " in t) if len(w) <= 3 else (w in t) for w in words):
            hits.append(slug)
    return hits

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


def _public(job, posted, featured=False):
    description = " ".join((job.get("description") or "").split())
    salary, contract, work = extract_details(job.get("title"), job.get("description"), job.get("location"))
    return {
        "featured": featured,
        "slug": job_slug(job.get("title") or "", job.get("url") or ""),
        "org_slug": slugify(job.get("company") or "unknown"),
        "location_class": location_class(job.get("location")),
        "salary": salary,
        "contract": contract,
        "work_type": work,
        "title": job.get("title") or "",
        "company": job.get("company") or "",
        "location": job.get("location") or "Not specified",
        "source": job.get("source") or "",
        "posted": posted.date().isoformat() if posted else None,
        "deadline": (job.get("deadline") or None),
        "url": job.get("url") or "",
        "excerpt": description[:220] + ("…" if len(description) > 220 else ""),
        # Longer text for the job page: full description for employer submissions, a summary otherwise.
        "body": (job.get("description") or "") if featured else (description[:700] + ("…" if len(description) > 700 else "")),
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
    # Employer postings approved by the owner: featured for their paid window, listed first.
    from .growth import live_employer_posts

    sponsored = []
    for p in live_employer_posts(db):
        posted = _parse(p.get("posted")) or _parse(p.get("created")) or now
        job = _public(p, posted, featured=True)
        job["source"] = "Featured employer"
        key = (p.get("url") or "").lower().rstrip("/")
        seen.pop(key, None)
        sponsored.append({"job": job, "posted": posted, "interest": 10**6, "created": posted})
    entries = sponsored + list(seen.values())
    for e in entries:
        e["job"]["sectors"] = sector_of(e["job"]["title"])
    latest = sorted(entries, key=lambda e: (e["job"]["featured"], e["posted"]), reverse=True)
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
        "sectors": {slug: sum(1 for e in entries if slug in e["job"]["sectors"]) for slug in SECTORS},
        # Server-side only (job pages, directory, sitemap); the public API strips it.
        "_all": [e["job"] for e in latest[:300]],
        "_by_slug": {e["job"]["slug"]: e["job"] for e in latest[:300]},
        "_orgs": organisations([e["job"] for e in latest[:300]]),
    }


def organisations(jobs):
    groups = {}
    for j in jobs:
        if not j.get("company"):
            continue
        g = groups.setdefault(j["org_slug"], {"slug": j["org_slug"], "name": j["company"], "count": 0, "locations": [], "sectors": set()})
        g["count"] += 1
        if j["location"] and j["location"] != "Not specified" and j["location"] not in g["locations"]:
            g["locations"].append(j["location"][:40])
        g["sectors"].update(j.get("sectors", []))
    out = []
    for g in groups.values():
        g["sectors"] = sorted(g["sectors"])
        g["locations"] = g["locations"][:4]
        out.append(g)
    return sorted(out, key=lambda g: (-g["count"], g["name"].lower()))


def public_view(data):
    strip = ("body",)
    return {k: ([{kk: vv for kk, vv in j.items() if kk not in strip} for j in v] if isinstance(v, list) else v) for k, v in data.items() if not k.startswith("_")}


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
        if j.get("featured"):
            badge = '<span class="job-badge featured">Featured</span>' + badge
        when = ago(j.get("posted"))
        details = " · ".join(x for x in (j.get("contract"), j.get("work_type"), j.get("salary")) if x)
        meta = " · ".join(x for x in (html.escape(j.get("source") or ""), ("Posted " + when) if when else "", html.escape(details)) if x)
        new_badge = '<span class="job-badge new">New</span>' if fresh else ""
        sep = " · " if j["company"] and j["location"] else ""
        href = "/job/" + j["slug"] if j.get("slug") else j["url"]
        out.append(
            '<article class="job-item">'
            f'<a class="job-link" href="{html.escape(href)}" data-title="{html.escape(j["title"])}">{html.escape(j["title"])}</a>'
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
        if j.get("slug"):
            posting["url"] = settings.public_url.rstrip("/") + "/job/" + j["slug"]
            posting["applicationContact"] = {"@type": "ContactPoint", "url": j["url"]}
        if j.get("work_type") == "Remote":
            posting["jobLocationType"] = "TELECOMMUTE"
        if j.get("contract"):
            posting["employmentType"] = {"Full-time": "FULL_TIME", "Part-time": "PART_TIME", "Internship": "INTERN", "Volunteer": "VOLUNTEER", "Consultancy": "CONTRACTOR", "Fixed-term": "TEMPORARY", "Fellowship": "OTHER"}.get(j["contract"], "OTHER")
        items.append({"@type": "ListItem", "position": i, "item": posting})
    data = {"@context": "https://schema.org", "@type": "ItemList", "name": "Latest jobs on Jobs Find AI", "url": site, "itemListElement": items}
    return '<script type="application/ld+json">' + json.dumps(data, ensure_ascii=False).replace("</", "<\\/") + "</script>"


# --- sector pages and sitemap -------------------------------------------------------

PAGE_CSS = """
:root{--ink:#13201b;--ink-2:#3b4a44;--muted:#6b7a73;--line:#e3e6e1;--paper:#f7f6f2;--green:#2f5d4a;--gold-soft:#f7efdd}
*{box-sizing:border-box}body{margin:0;font-family:Inter,system-ui,sans-serif;background:var(--paper);color:var(--ink);line-height:1.5}
.wrap{max-width:1100px;margin:0 auto;padding:0 20px}.nav{display:flex;justify-content:space-between;align-items:center;padding:16px 0;border-bottom:1px solid var(--line)}
.nav a{color:var(--ink);text-decoration:none;font-weight:600}.nav .btn{background:var(--green);color:#fff;padding:10px 16px;border-radius:999px}
h1{font-family:Georgia,serif;font-size:2rem;margin:36px 0 8px}.lead{color:var(--ink-2);max-width:60ch}.sectors{display:flex;flex-wrap:wrap;gap:8px;margin:18px 0 26px}
.sectors a{border:1px solid var(--line);background:#fff;border-radius:999px;padding:6px 12px;font-size:.85rem;color:var(--ink-2);text-decoration:none}.sectors a.on{background:var(--green);color:#fff;border-color:var(--green)}
.job-list{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}@media(max-width:900px){.job-list{grid-template-columns:repeat(2,1fr)}}@media(max-width:560px){.job-list{grid-template-columns:1fr}}
.job-item{background:#fff;border:1px solid var(--line);border-radius:16px;padding:18px;display:flex;flex-direction:column;gap:6px}.job-link{font-weight:700;color:var(--ink);text-decoration:none}
.job-org{font-size:.86rem;color:var(--ink-2);margin:0}.job-meta{font-size:.76rem;color:var(--muted);margin:auto 0 0;display:flex;flex-wrap:wrap;gap:8px}
.job-badge{padding:2px 8px;border-radius:999px;background:var(--gold-soft);color:#7a5a14;font-weight:600;font-size:.72rem}.job-badge.new{background:#e3efe8;color:var(--green)}.job-badge.urgent{background:#fbe4e1;color:#a1362a}.job-badge.featured{background:var(--green);color:#fff}
.cta{margin:36px 0 48px;padding:22px;background:#fff;border:1px solid var(--line);border-radius:16px;display:flex;justify-content:space-between;gap:16px;align-items:center;flex-wrap:wrap}
footer{color:var(--muted);font-size:.8rem;padding:24px 0 40px}
"""


def sector_page(data, slug=None):
    """A standalone, indexable page listing open roles for one sector (or all)."""
    if slug and slug not in SECTORS:
        return None
    jobs = data["_all"] if not slug else [j for j in data["_all"] if slug in j.get("sectors", [])]
    title = SECTORS[slug][0] if slug else "Open roles in data, climate, geospatial, agriculture and development"
    site = settings.public_url.rstrip("/")
    chips = '<a href="/jobs" class="%s">All (%d)</a>' % ("on" if not slug else "", len(data["_all"]))
    for s2, (label, _) in SECTORS.items():
        chips += ' <a href="/jobs/%s" class="%s">%s (%d)</a>' % (s2, "on" if s2 == slug else "", html.escape(label.split(" jobs")[0]), data["sectors"].get(s2, 0))
    head_title = f"{title} · {settings.app_name}"
    description = f"{len(jobs)} open {title.lower()}, collected from ReliefWeb and employer boards and refreshed every ten minutes. Get every posting scored against your verified CV."
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{html.escape(head_title)}</title><meta name=\"description\" content=\"{html.escape(description)}\">"
        f"<link rel=\"canonical\" href=\"{site}/jobs{'/' + slug if slug else ''}\"><link rel=\"icon\" href=\"/favicon.svg\" type=\"image/svg+xml\">"
        f"<meta property=\"og:title\" content=\"{html.escape(head_title)}\"><meta property=\"og:description\" content=\"{html.escape(description)}\"><meta property=\"og:image\" content=\"{site}/social-card.png\">"
        f"<style>{PAGE_CSS}</style>{json_ld(jobs[:25], site + '/jobs' + ('/' + slug if slug else ''))}</head><body><div class=\"wrap\">"
        f"<nav class=\"nav\"><a href=\"/\">{html.escape(settings.app_name)}</a><a class=\"btn\" href=\"/#invite\">Get matched</a></nav>"
        f"<h1>{html.escape(title)}</h1><p class=\"lead\">{html.escape(description)}</p><div class=\"sectors\">{chips}</div>"
        f"<div class=\"job-list\">{render_cards(jobs)}</div>"
        f"<div class=\"cta\"><div><b>Stop scrolling boards.</b> {html.escape(settings.app_name)} scores every one of these against the verified facts in your CV and explains the fit.</div><a class=\"btn\" style=\"background:var(--green);color:#fff;padding:12px 18px;border-radius:999px;text-decoration:none;font-weight:600\" href=\"/#invite\">Request an invite</a></div>"
        f"<footer>{html.escape(settings.app_name)} · Public postings only, linking to the employer's page. <a href=\"/privacy.html\">Privacy</a> · <a href=\"/terms.html\">Terms</a></footer>"
        "</div></body></html>"
    )


def sitemap(data):
    site = settings.public_url.rstrip("/")
    today = datetime.now(timezone.utc).date().isoformat()
    urls = [(site + "/", "daily", "1.0"), (site + "/jobs", "hourly", "0.9")] + [(site + "/jobs/" + s2, "hourly", "0.8") for s2 in SECTORS] + [(site + "/privacy.html", "monthly", "0.2"), (site + "/terms.html", "monthly", "0.2")]
    body = "".join(f"<url><loc>{html.escape(u)}</loc><lastmod>{today}</lastmod><changefreq>{f}</changefreq><priority>{p}</priority></url>" for u, f, p in urls)
    return '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + body + "</urlset>"
