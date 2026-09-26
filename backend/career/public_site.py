"""Public, indexable pages built from the public listings: a page per job with
sharing, the searchable listing index, the organisations directory and the
guide. Everything shares one page shell with the landing page's look."""

import html
import json
import math
from datetime import datetime, timezone
from urllib.parse import quote, urlencode
from .config import settings
from . import public_jobs as pj
from . import guide

PER_PAGE = 24
LOCATIONS = {"ethiopia": "Ethiopia", "africa": "Elsewhere in Africa", "remote": "Remote", "other": "Other countries"}
CLOSING = {"7": "within 7 days", "14": "within 14 days", "30": "within 30 days"}

CSS = pj.PAGE_CSS + """
.filters{display:grid;grid-template-columns:2fr 1fr 1fr 1fr 1fr auto;gap:8px;margin:18px 0 22px;align-items:end}
.filters label{display:grid;gap:4px;font-size:.78rem;font-weight:600;color:var(--ink-2)}.filters input,.filters select{padding:10px 12px;border:1px solid var(--line);border-radius:10px;background:#fff;font:inherit;font-size:.9rem;min-width:0}
.filters button{padding:11px 16px;border-radius:999px;border:none;background:var(--green);color:#fff;font:inherit;font-weight:600;cursor:pointer}
@media(max-width:900px){.filters{grid-template-columns:1fr 1fr}}@media(max-width:560px){.filters{grid-template-columns:1fr}}
.count{color:var(--muted);font-size:.9rem;margin-bottom:12px}.pager{display:flex;gap:10px;justify-content:center;margin:26px 0}.pager a,.pager span{padding:8px 14px;border:1px solid var(--line);border-radius:999px;background:#fff;color:var(--ink);text-decoration:none;font-size:.9rem}.pager span{color:var(--muted)}
.job-head{display:flex;justify-content:space-between;gap:24px;align-items:flex-start;flex-wrap:wrap;margin-top:32px}.job-head h1{margin:8px 0 6px}.job-head .org{font-size:1.05rem;color:var(--ink-2)}
.facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin:22px 0}.fact{background:#fff;border:1px solid var(--line);border-radius:14px;padding:12px 14px}.fact small{display:block;color:var(--muted);font-size:.72rem;letter-spacing:.08em;text-transform:uppercase;font-weight:700}.fact b{font-weight:600}
.apply{display:inline-flex;align-items:center;gap:8px;background:var(--green);color:#fff;padding:12px 20px;border-radius:999px;text-decoration:none;font-weight:600}.ghost{display:inline-flex;align-items:center;gap:8px;border:1px solid var(--line);background:#fff;color:var(--ink);padding:11px 18px;border-radius:999px;text-decoration:none;font-weight:600}
.actions{display:flex;gap:10px;flex-wrap:wrap;margin:8px 0 20px}.body{background:#fff;border:1px solid var(--line);border-radius:16px;padding:22px 24px;line-height:1.65;max-width:78ch}.body p{margin:0 0 12px}
.share{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:22px 0;font-size:.86rem;color:var(--muted)}.share a{border:1px solid var(--line);background:#fff;border-radius:999px;padding:7px 12px;color:var(--ink);text-decoration:none;font-weight:600;font-size:.82rem}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}.chip{font-size:.74rem;padding:3px 9px;border-radius:999px;background:#eef2ee;color:var(--ink-2);font-weight:600}
h2.sub{font-family:Georgia,serif;font-size:1.35rem;margin:34px 0 12px}
.orgs{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}@media(max-width:900px){.orgs{grid-template-columns:repeat(2,1fr)}}@media(max-width:560px){.orgs{grid-template-columns:1fr}}
.org{background:#fff;border:1px solid var(--line);border-radius:16px;padding:18px;display:flex;gap:14px;align-items:flex-start;text-decoration:none;color:var(--ink)}.org .mono{width:44px;height:44px;border-radius:12px;background:var(--green);color:#fff;display:grid;place-items:center;font-weight:700;flex:none}.org b{display:block}.org small{color:var(--muted)}
.articles{display:grid;grid-template-columns:repeat(2,1fr);gap:16px}@media(max-width:700px){.articles{grid-template-columns:1fr}}.article{background:#fff;border:1px solid var(--line);border-radius:16px;padding:22px;text-decoration:none;color:var(--ink)}.article b{display:block;font-size:1.05rem;margin-bottom:6px}.article p{color:var(--ink-2);margin:0 0 8px;font-size:.95rem}.article small{color:var(--muted)}
.prose{max-width:72ch;line-height:1.7}.prose h2{font-family:Georgia,serif;font-size:1.35rem;margin:30px 0 10px}.prose p,.prose li{color:var(--ink-2)}.prose ol,.prose ul{padding-left:22px}
.banner{margin:40px 0 8px;background:linear-gradient(120deg,#2f5d4a,#1f3f33);color:#fff;border-radius:22px;padding:28px 30px;display:flex;align-items:center;gap:22px;flex-wrap:wrap}
.banner .ico{width:56px;height:56px;border-radius:14px;background:rgba(255,255,255,.14);display:grid;place-items:center;flex:none}.banner .ico svg{width:28px;height:28px}
.banner .txt{flex:1;min-width:240px}.banner b{display:block;font-family:Georgia,serif;font-size:1.45rem;line-height:1.15;margin-bottom:6px}.banner p{margin:0;color:rgba(255,255,255,.82)}
.banner .cta{background:#fff;color:#1f3f33;padding:12px 20px;border-radius:999px;text-decoration:none;font-weight:700;display:inline-flex;gap:8px;align-items:center;margin:0}
"""


def site():
    return settings.public_url.rstrip("/")


def channel_url():
    cid = settings.telegram_channel_id.strip()
    return "https://t.me/" + cid[1:] if cid.startswith("@") else ""


def channel_banner():
    """A band inviting people to the Telegram channel. Empty when no channel is configured."""
    url = channel_url()
    if not url:
        return ""
    return (
        '<div class="banner"><div class="ico"><svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 3 3 10.5l7 2.5 2.5 7L21 3z"/><path d="M10 13l11-10"/></svg></div>'
        f'<div class="txt"><b>New roles in your field, on your phone every morning</b><p>The {html.escape(settings.app_name)} channel posts fresh data, climate, geospatial, agriculture and development roles daily, and what closes this week on Mondays. Free, no spam.</p></div>'
        f'<a class="cta" href="{html.escape(url, quote=True)}" target="_blank" rel="noopener" data-track="channel_link_clicked">Join on Telegram</a></div>'
    )


def shell(title, description, body, path, extra_head="", image=None):
    nav_links = ' <a href="/jobs">Jobs</a> <a href="/organisations">Employers</a> <a href="/guide">Guide</a>'
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{html.escape(title)} · {html.escape(settings.app_name)}</title><meta name=\"description\" content=\"{html.escape(description)}\">"
        f'<link rel="canonical" href="{site()}{path}"><link rel="icon" href="/favicon.svg" type="image/svg+xml">'
        f'<meta property="og:title" content="{html.escape(title)}"><meta property="og:description" content="{html.escape(description)}"><meta property="og:image" content="{html.escape(image or site() + "/social-card.png")}"><meta property="og:url" content="{site()}{path}"><meta name="twitter:card" content="summary_large_image">'
        f"<style>{CSS}</style>{extra_head}</head><body><div class=\"wrap\">"
        f'<nav class="nav"><a href="/">{html.escape(settings.app_name)}</a><span style="display:flex;gap:18px;align-items:center;font-size:.92rem">{nav_links}<a class="btn" href="/#invite">Get matched</a></span></nav>'
        f"{body}{channel_banner()}"
        f'<footer>{html.escape(settings.app_name)} · Public postings link to the employer\'s own page. <a href="/privacy.html">Privacy</a> · <a href="/terms.html">Terms</a></footer>'
        '</div><script>document.querySelectorAll("[data-track]").forEach(function(e){e.addEventListener("click",function(){try{window.posthog&&posthog.capture(e.dataset.track,{page:location.pathname})}catch(_){}})});</script></body></html>'
    )


# --- listing index with search, filters and pagination ---------------------------------


def filter_jobs(data, q="", sector="", location="", org="", closing=""):
    jobs = data["_all"]
    q = (q or "").strip().lower()
    if q:
        jobs = [j for j in jobs if q in (j["title"] + " " + j["company"] + " " + j["location"]).lower()]
    if sector in pj.SECTORS:
        jobs = [j for j in jobs if sector in j.get("sectors", [])]
    if location in LOCATIONS:
        jobs = [j for j in jobs if j.get("location_class") == location]
    if org:
        jobs = [j for j in jobs if j.get("org_slug") == org]
    if closing in CLOSING:
        limit = int(closing)
        jobs = [j for j in jobs if j.get("deadline") and (pj._days_left(j["deadline"]) or 0) <= limit and (pj._days_left(j["deadline"]) or 0) >= 0]
    return jobs


def jobs_index(data, params):
    q, sector, location, org, closing = (params.get(k, "") or "" for k in ("q", "sector", "location", "org", "closing"))
    try:
        page = max(1, int(params.get("page") or 1))
    except ValueError:
        page = 1
    jobs = filter_jobs(data, q, sector, location, org, closing)
    pages = max(1, math.ceil(len(jobs) / PER_PAGE))
    page = min(page, pages)
    chunk = jobs[(page - 1) * PER_PAGE : page * PER_PAGE]
    orgs = {o["slug"]: o["name"] for o in data["_orgs"]}
    opt = lambda items, cur: "".join(f'<option value="{html.escape(k)}" {"selected" if k == cur else ""}>{html.escape(v)}</option>' for k, v in items)
    form = (
        '<form class="filters" method="get" action="/jobs">'
        f'<label>Search<input type="search" name="q" value="{html.escape(q)}" placeholder="Title, employer or location"></label>'
        f'<label>Field<select name="sector"><option value="">All fields</option>{opt([(k, v[0].replace(" jobs", "")) for k, v in pj.SECTORS.items()], sector)}</select></label>'
        f'<label>Location<select name="location"><option value="">Anywhere</option>{opt(LOCATIONS.items(), location)}</select></label>'
        f'<label>Employer<select name="org"><option value="">All employers</option>{opt(sorted(orgs.items(), key=lambda x: x[1].lower()), org)}</select></label>'
        f'<label>Closing<select name="closing"><option value="">Any date</option>{opt(CLOSING.items(), closing)}</select></label>'
        "<button type=\"submit\">Filter</button></form>"
    )
    keep = {k: v for k, v in (("q", q), ("sector", sector), ("location", location), ("org", org), ("closing", closing)) if v}
    link = lambda p: "/jobs?" + urlencode({**keep, "page": p})
    pager = ""
    if pages > 1:
        pager = '<div class="pager">' + (f'<a href="{link(page - 1)}">← Previous</a>' if page > 1 else "") + f"<span>Page {page} of {pages}</span>" + (f'<a href="{link(page + 1)}">Next →</a>' if page < pages else "") + "</div>"
    title = "Open roles in data, climate, geospatial, agriculture and development"
    if sector in pj.SECTORS:
        title = pj.SECTORS[sector][0]
    if org in orgs:
        title = f"Open roles at {orgs[org]}"
    description = f"{len(jobs)} open postings, collected from ReliefWeb and employer boards and refreshed every ten minutes. Filter by field, location, employer and closing date."
    body = f"<h1>{html.escape(title)}</h1><p class=\"lead\">{html.escape(description)}</p>{form}<p class=\"count\">{len(jobs)} posting{'s' if len(jobs) != 1 else ''}{' · ' + str(data['listed_last_7_days']) + ' new this week' if not keep else ''}</p><div class=\"job-list\">{pj.render_cards(chunk)}</div>{pager}"
    return shell(title, description, body, "/jobs" + ("?" + urlencode(keep) if keep else ""), extra_head=pj.json_ld(chunk, site() + "/jobs"))


# --- one job ------------------------------------------------------------------------


def share_links(j):
    url = f"{site()}/job/{j['slug']}"
    text = f"{j['title']} at {j['company']}" if j["company"] else j["title"]
    tg = "https://t.me/share/url?" + urlencode({"url": url, "text": text})
    wa = "https://wa.me/?" + urlencode({"text": text + "\n" + url})
    li = "https://www.linkedin.com/sharing/share-offsite/?" + urlencode({"url": url})
    mail = "mailto:?" + urlencode({"subject": text, "body": url}).replace("+", "%20")
    return (
        '<div class="share"><span>Share:</span>'
        f'<a href="{html.escape(tg)}" target="_blank" rel="noopener" data-track="job_shared">Telegram</a>'
        f'<a href="{html.escape(wa)}" target="_blank" rel="noopener" data-track="job_shared">WhatsApp</a>'
        f'<a href="{html.escape(li)}" target="_blank" rel="noopener" data-track="job_shared">LinkedIn</a>'
        f'<a href="{html.escape(mail)}" data-track="job_shared">Email</a>'
        f'<a href="#" onclick="navigator.clipboard&&navigator.clipboard.writeText({json.dumps(url)});this.textContent=\'Copied\';return false" data-track="job_shared">Copy link</a></div>'
    )


def job_page(data, slug):
    j = data["_by_slug"].get(slug)
    if not j:
        return None
    left = pj._days_left(j.get("deadline"))
    closes = "No closing date given" if left is None else ("Closed" if left < 0 else "Today" if left == 0 else f"In {left} day{'s' if left != 1 else ''} ({j['deadline'][:10]})")
    facts = [("Employer", j["company"] or "See posting"), ("Location", j["location"]), ("Closing", closes), ("Posted", pj.ago(j.get("posted")) or "recently")]
    if j.get("contract"):
        facts.append(("Contract", j["contract"]))
    if j.get("work_type"):
        facts.append(("Work", j["work_type"]))
    if j.get("salary"):
        facts.append(("Salary", j["salary"]))
    facts_html = "".join(f'<div class="fact"><small>{html.escape(k)}</small><b>{html.escape(v)}</b></div>' for k, v in facts)
    chips = "".join(f'<a class="chip" href="/jobs/{s}">{html.escape(pj.SECTORS[s][0].replace(" jobs", ""))}</a>' for s in j.get("sectors", []))
    source_note = (
        "<p><em>This vacancy was submitted by the employer and is featured for two weeks.</em></p>" if j.get("featured") else f'<p><em>Summary of the public posting on {html.escape(j["source"])}. Read the full text and apply on the employer\'s page.</em></p>'
    )
    paragraphs = "".join(f"<p>{html.escape(p)}</p>" for p in (j.get("body") or j.get("excerpt") or "").split("\n\n") if p.strip())
    same_org = [x for x in data["_all"] if x.get("org_slug") == j.get("org_slug") and x["slug"] != slug][:3]
    similar = [x for x in data["_all"] if x["slug"] != slug and set(x.get("sectors", [])) & set(j.get("sectors", []))][:6]
    related = ""
    if same_org:
        related += f'<h2 class="sub">More from {html.escape(j["company"])}</h2><div class="job-list">{pj.render_cards(same_org)}</div>'
    if similar:
        related += '<h2 class="sub">Similar roles</h2><div class="job-list">' + pj.render_cards(similar) + "</div>"
    featured_chip = '<span class="chip" style="background:var(--green);color:#fff">Featured</span>' if j.get("featured") else ""
    body = (
        f'<div class="job-head"><div><div class="chips">{chips}{featured_chip}</div>'
        f'<h1>{html.escape(j["title"])}</h1><div class="org">{html.escape(j["company"])}{" · " if j["company"] and j["location"] else ""}{html.escape(j["location"])}</div></div></div>'
        f'<div class="facts">{facts_html}</div>'
        f'<div class="actions"><a class="apply" href="{html.escape(j["url"])}" target="_blank" rel="noopener nofollow" data-track="job_apply_clicked">Apply on the employer\'s page ↗</a>'
        f'<a class="ghost" href="/app/?job_url={quote(j["url"], safe="")}" data-track="job_match_clicked">See how you match</a></div>'
        f'<div class="body">{source_note}{paragraphs}</div>{share_links(j)}{related}'
    )
    description = (j.get("excerpt") or j["title"])[:155]
    ld = pj.json_ld([j], site() + "/job/" + slug)
    return shell(f'{j["title"]} at {j["company"]}' if j["company"] else j["title"], description, body, "/job/" + slug, extra_head=ld)


# --- organisations ----------------------------------------------------------------------


def org_index(data):
    orgs = data["_orgs"]
    cards = "".join(
        f'<a class="org" href="/organisations/{o["slug"]}"><span class="mono">{html.escape(o["name"][:1].upper())}</span><span><b>{html.escape(o["name"])}</b><small>{o["count"]} open role{"s" if o["count"] != 1 else ""}{(" · " + ", ".join(o["locations"][:2])) if o["locations"] else ""}</small></span></a>'
        for o in orgs
    )
    title = "Employers hiring in data, climate, geospatial, agriculture and development"
    description = f"{len(orgs)} organisations with open roles right now, from UN agencies and NGOs to research centres and remote-first companies."
    cards = cards or '<p class="count">No open roles at the moment.</p>'
    body = f'<h1>{html.escape(title)}</h1><p class="lead">{html.escape(description)}</p><div class="orgs" style="margin-top:24px">{cards}</div>'
    return shell("Employers", description, body, "/organisations")


def org_page(data, slug):
    o = next((x for x in data["_orgs"] if x["slug"] == slug), None)
    if not o:
        return None
    jobs = [j for j in data["_all"] if j.get("org_slug") == slug]
    description = f"{o['count']} open role{'s' if o['count'] != 1 else ''} at {o['name']}" + (", in " + ", ".join(o["locations"][:3]) if o["locations"] else "") + ". Each one scored against your verified CV when you join."
    body = f"<h1>{html.escape(o['name'])}</h1><p class=\"lead\">{html.escape(description)}</p><div class=\"job-list\" style=\"margin-top:24px\">{pj.render_cards(jobs)}</div>"
    return shell(f"Jobs at {o['name']}", description, body, "/organisations/" + slug, extra_head=pj.json_ld(jobs[:25], site() + "/organisations/" + slug))


# --- guide -----------------------------------------------------------------------------


def guide_index():
    cards = "".join(f'<a class="article" href="/guide/{a["slug"]}"><b>{html.escape(a["title"])}</b><p>{html.escape(a["summary"])}</p><small>{a["minutes"]} min read</small></a>' for a in guide.ARTICLES)
    description = "Practical, short guides for data, climate, geospatial, agriculture and development job seekers: where roles appear, CVs that pass screening, NGO and UN applications, interviews."
    body = f"<h1>Job seeker's guide</h1><p class=\"lead\">{html.escape(description)}</p><div class=\"articles\" style=\"margin-top:24px\">{cards}</div>"
    return shell("Job seeker's guide", description, body, "/guide")


def guide_page(slug):
    a = guide.by_slug(slug)
    if not a:
        return None
    ld = json.dumps({"@context": "https://schema.org", "@type": "Article", "headline": a["title"], "description": a["summary"], "author": {"@type": "Organization", "name": settings.app_name}, "publisher": {"@type": "Organization", "name": settings.app_name}, "mainEntityOfPage": site() + "/guide/" + slug}, ensure_ascii=False)
    body = (
        f'<p class="count" style="margin-top:28px"><a href="/guide">Guide</a> · {a["minutes"]} min read</p><h1>{html.escape(a["title"])}</h1><p class="lead">{html.escape(a["summary"])}</p><div class="prose">{a["body"]}</div>'
        f'<div class="cta"><div><b>Put it into practice.</b> {html.escape(settings.app_name)} watches the boards, scores each posting against your verified CV and drafts applications you review.</div><a class="apply" href="/#invite">Request an invite</a></div>'
    )
    return shell(a["title"], a["summary"], body, "/guide/" + slug, extra_head='<script type="application/ld+json">' + ld.replace("</", "<\\/") + "</script>")


def sitemap(data):
    today = datetime.now(timezone.utc).date().isoformat()
    urls = [(site() + "/", "daily", "1.0"), (site() + "/jobs", "hourly", "0.9"), (site() + "/organisations", "daily", "0.6"), (site() + "/guide", "weekly", "0.6")]
    urls += [(site() + "/jobs/" + s, "hourly", "0.8") for s in pj.SECTORS]
    urls += [(site() + "/job/" + j["slug"], "daily", "0.7") for j in data["_all"]]
    urls += [(site() + "/organisations/" + o["slug"], "daily", "0.5") for o in data["_orgs"]]
    urls += [(site() + "/guide/" + a["slug"], "monthly", "0.5") for a in guide.ARTICLES]
    urls += [(site() + "/privacy.html", "monthly", "0.2"), (site() + "/terms.html", "monthly", "0.2")]
    body = "".join(f"<url><loc>{html.escape(u)}</loc><lastmod>{today}</lastmod><changefreq>{f}</changefreq><priority>{p}</priority></url>" for u, f, p in urls)
    return '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + body + "</urlset>"
