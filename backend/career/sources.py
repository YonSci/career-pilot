"""Job source connectors.

Each connector receives an HTTP client, the configured value and a Context, and
returns a list of JobInput dictionaries. Connectors that read individual public
posting pages (ReliefWeb RSS fallback, generic RSS, career pages) go through
Context.fetch_page, which enforces a per-run budget and a delay between
requests. A posting whose URL is already stored is returned as a "partial"
entry so the run can refresh last_seen without re-downloading or re-evaluating.
"""

import base64
import contextvars
import ipaddress
import socket
from concurrent.futures import ThreadPoolExecutor
import email
import email.policy
import imaplib
import logging
import re
import time
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse, urljoin
from xml.etree import ElementTree as ET
import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel
from .schemas import JobInput
from .config import settings
from .db import current_user
from .ai import structured, ai_available

log = logging.getLogger(__name__)
USER_AGENT = "JobsFindAI/0.3 personal-job-assistant"
UNAVAILABLE = "Description unavailable. Review the employer posting."
MAX_PAGE_BYTES = 3_000_000
MAX_REDIRECTS = 5


def resolve_host(host):
    """All addresses a hostname resolves to (patched in tests)."""
    try:
        return sorted({info[4][0] for info in socket.getaddrinfo(host, None)})
    except socket.gaierror:
        raise ValueError(f"The host {host} could not be resolved.")


def validated_addresses(url):
    """Resolve the URL's host ONCE and validate every returned address.
    Returns (url, addresses); addresses is empty for a literal-IP host that passed."""
    url = clean_url((url or "").strip())
    if not url:
        raise ValueError("Enter a full public http(s) address.")
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if host in ("localhost",) or host.endswith(".localhost") or host.endswith(".local") or host.endswith(".internal"):
        raise ValueError("Local or private addresses cannot be used as sources.")
    try:
        ipaddress.ip_address(host)
        literal = True
        candidates = [host]
    except ValueError:
        literal = False
        candidates = resolve_host(host)
    if not candidates:
        raise ValueError(f"The host {host} could not be resolved.")
    for address in candidates:
        try:
            ip = ipaddress.ip_address(address.split("%")[0])
        except ValueError:
            raise ValueError("The address could not be checked.")
        if not ip.is_global or ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            raise ValueError("That address points to a private or local network and cannot be used as a source.")
    return url, ([] if literal else candidates)


def public_url(url):
    """Accept only http(s) URLs whose host resolves to public addresses.
    Prevents a configured source from pointing the server at internal services."""
    return validated_addresses(url)[0]


def assert_public_peer(response):
    """After the connection is made, confirm the address actually connected to is
    public. Closes the window between the DNS check and the connection (rebinding)."""
    stream = response.extensions.get("network_stream")
    if stream is None:
        return  # mocked transport
    try:
        peer = stream.get_extra_info("server_addr")
    except Exception:
        return
    if not peer:
        return
    address = peer[0].split("%")[0]
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return
    if not ip.is_global or ip.is_private or ip.is_loopback or ip.is_link_local:
        raise ValueError("That address points to a private or local network and cannot be used as a source.")


def pinned_request(url):
    """Resolve and validate `url`, then return (pinned_url, headers, extensions)
    that connect to the validated address while keeping the hostname for the
    Host header and TLS verification. DNS cannot change the target afterwards."""
    url, addresses = validated_addresses(url)
    if not addresses:
        return url, {}, {}
    parsed = urlparse(url)
    host = parsed.hostname or ""
    # Same resolution result that was validated: no second lookup can swap the target.
    address = addresses[0]
    literal = f"[{address}]" if ":" in address else address
    netloc = literal + (f":{parsed.port}" if parsed.port else "")
    pinned = parsed._replace(netloc=netloc).geturl()
    host_header = host + (f":{parsed.port}" if parsed.port else "")
    return pinned, {"Host": host_header}, {"sni_hostname": host}


def safe_get(client, url, accept=None):
    """GET with manual redirects so every hop is validated and pinned before the
    request is sent, a post-connect peer check, and a bound on the response size.
    The returned response carries decoded bytes, so encoding headers are dropped."""
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        pinned, host_headers, extensions = pinned_request(current)
        headers = {**host_headers, **({"Accept": accept} if accept else {})}
        with client.stream("GET", pinned, follow_redirects=False, headers=headers, extensions=extensions) as r:
            assert_public_peer(r)
            if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                current = public_url(urljoin(current, r.headers["location"]))
                continue
            r.raise_for_status()
            content = bytearray()
            for chunk in r.iter_bytes():  # decoded (gzip/br handled by httpx)
                content.extend(chunk)
                if len(content) >= MAX_PAGE_BYTES:
                    break
            headers = {k: v for k, v in r.headers.items() if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")}
            return httpx.Response(r.status_code, headers=headers, content=bytes(content[:MAX_PAGE_BYTES]), request=r.request)
    raise ValueError("Too many redirects.")


def plain(html):
    return BeautifulSoup(html or "", "html.parser").get_text("\n", strip=True)


def page_text(html):
    """Readable text of a public web page: main content without chrome."""
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "form", "aside", "svg", "iframe"]):
        tag.decompose()
    root = soup.find("main") or soup.find("article") or soup.body or soup
    text = root.get_text("\n", strip=True)
    return re.sub(r"\n{3,}", "\n\n", text)


def clean_url(url):
    if not url:
        return ""
    parsed = urlparse(url)
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError("Use an ordinary HTTP or HTTPS job link.")
    return url


def board_slug(value):
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", value or ""):
        raise ValueError(
            "Enter the employer board identifier, for example acme, rather than a URL."
        )
    return value


def http_url(value):
    try:
        return clean_url((value or "").strip())
    except ValueError:
        raise ValueError("Enter a full public http(s) address.")


def iso(value):
    """Normalise the many date formats feeds use into ISO 8601, or None."""
    if value in (None, "", 0):
        return None
    try:
        if isinstance(value, (int, float)):
            ts = value / 1000 if value > 10_000_000_000 else value
            return datetime.fromtimestamp(ts, timezone.utc).isoformat()
        text = str(value).strip()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            return text
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            parsed = parsedate_to_datetime(text)
        return parsed.isoformat()
    except (ValueError, TypeError, OverflowError):
        return None


class JobBatch(BaseModel):
    jobs: list[JobInput]


class Context:
    """Per-run limits shared by all connectors."""

    def __init__(self, known_urls=None, seen_mail=None, page_budget=None, delay=None, sample=False, deadline=None):
        # sample=True: a quick "Test source" read that touches only a few items.
        self.sample = sample
        # Connectors stop paging and fetching once the search's time budget is used up.
        self.deadline = deadline
        self.known_urls = set(known_urls or ())
        self.seen_mail = set(seen_mail or ())
        self.page_budget = settings.max_page_fetches_per_run if page_budget is None else page_budget
        self.delay = settings.fetch_delay_seconds if delay is None else delay
        self.pages_fetched = 0
        self.skipped_for_budget = 0
        self.mail_ids = []
        self._last = 0.0

    def out_of_time(self):
        return self.deadline is not None and datetime.now(timezone.utc) >= self.deadline

    def fetch_page(self, client, url):
        """Read one public page, or None once the page or time budget is spent."""
        if self.pages_fetched >= self.page_budget or self.out_of_time():
            self.skipped_for_budget += 1
            return None
        wait = self.delay - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        self.pages_fetched += 1
        r = safe_get(client, url)
        if "html" not in r.headers.get("content-type", "") and "xml" not in r.headers.get("content-type", ""):
            return None
        return page_text(r.text)[:60000]

    def partial(self, url):
        return {"url": url, "partial": True}


def job(**fields):
    fields["description"] = (fields.get("description") or "").strip() or UNAVAILABLE
    if len(fields["description"]) < 30:
        fields["description"] = fields["description"] + "\n" + UNAVAILABLE
    fields["description"] = fields["description"][:60000]
    fields["title"] = (fields.get("title") or "Untitled posting")[:240]
    fields["company"] = (fields.get("company") or "")[:240]
    fields["location"] = (fields.get("location") or "Not specified")[:240]
    return JobInput(**fields).model_dump()


# --- Employer applicant-tracking systems with public JSON APIs -----------------


def greenhouse(client, value, ctx):
    slug = board_slug(value)
    r = client.get(
        f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
        params={"content": "true"},
    )
    r.raise_for_status()
    return [
        job(
            title=item["title"],
            company=slug,
            location=(item.get("location") or {}).get("name"),
            description=plain(item.get("content")),
            url=clean_url(item["absolute_url"]),
            source="Greenhouse",
            external_id=f"{slug}:{item['id']}",
            posted=iso(item.get("updated_at") or item.get("first_published")),
        )
        for item in r.json().get("jobs", [])
    ]


def lever(client, value, ctx):
    slug = board_slug(value)
    jobs, skip = [], 0
    while True:
        r = client.get(
            f"https://api.lever.co/v0/postings/{slug}",
            params={"mode": "json", "limit": 100, "skip": skip},
        )
        r.raise_for_status()
        batch = r.json()
        for item in batch:
            desc = item.get("descriptionPlain") or plain(item.get("description"))
            for part in item.get("lists", []):
                desc += "\n" + part.get("text", "") + "\n" + plain(part.get("content"))
            desc += "\n" + (item.get("additionalPlain") or plain(item.get("additional")))
            jobs.append(
                job(
                    title=item["text"],
                    company=slug,
                    location=(item.get("categories") or {}).get("location"),
                    description=desc,
                    url=clean_url(item["hostedUrl"]),
                    source="Lever",
                    external_id=item["id"],
                    posted=iso(item.get("createdAt")),
                )
            )
        if len(batch) < 100 or skip >= 5000 or ctx.out_of_time():
            break
        skip += 100
    return jobs


def workable(client, value, ctx):
    slug = board_slug(value)
    r = client.post(f"https://apply.workable.com/api/v3/accounts/{slug}/jobs", json={})
    r.raise_for_status()
    jobs = []
    for item in r.json().get("results", []):
        code = item.get("shortcode")
        url = f"https://apply.workable.com/{slug}/j/{code}/"
        if url in ctx.known_urls:
            jobs.append(ctx.partial(url))
            continue
        if ctx.out_of_time():
            break
        detail = client.get(f"https://apply.workable.com/api/v2/accounts/{slug}/jobs/{code}")
        detail.raise_for_status()
        d = detail.json()
        loc = item.get("location") or {}
        location = ", ".join(x for x in (loc.get("city"), loc.get("country")) if x)
        if item.get("workplace") == "remote":
            location = ("Remote, " + location) if location else "Remote"
        description = "\n\n".join(
            plain(d.get(k)) for k in ("description", "requirements", "benefits") if d.get(k)
        )
        jobs.append(
            job(
                title=item.get("title"),
                company=slug,
                location=location,
                description=description,
                url=url,
                source="Workable",
                external_id=f"{slug}:{code}",
                posted=iso(item.get("published")),
            )
        )
    return jobs


def smartrecruiters(client, value, ctx):
    company = board_slug(value)
    jobs, offset = [], 0
    while True:
        r = client.get(
            f"https://api.smartrecruiters.com/v1/companies/{company}/postings",
            params={"limit": 100, "offset": offset},
        )
        r.raise_for_status()
        data = r.json()
        content = data.get("content", [])
        for item in content:
            url = f"https://jobs.smartrecruiters.com/{company}/{item['id']}"
            if url in ctx.known_urls:
                jobs.append(ctx.partial(url))
                continue
            detail = client.get(item.get("ref") or f"https://api.smartrecruiters.com/v1/companies/{company}/postings/{item['id']}")
            detail.raise_for_status()
            d = detail.json()
            sections = (d.get("jobAd") or {}).get("sections") or {}
            description = "\n\n".join(
                (s.get("title", "") + "\n" + plain(s.get("text")))
                for s in sections.values()
                if isinstance(s, dict) and s.get("text")
            )
            loc = item.get("location") or {}
            location = ", ".join(x for x in (loc.get("city"), loc.get("country")) if x)
            if loc.get("remote"):
                location = ("Remote, " + location) if location else "Remote"
            jobs.append(
                job(
                    title=item.get("name"),
                    company=(item.get("company") or {}).get("name") or company,
                    location=location,
                    description=description,
                    url=d.get("applyUrl") and clean_url(d["applyUrl"]) or url,
                    source="SmartRecruiters",
                    external_id=f"{company}:{item['id']}",
                    posted=iso(item.get("releasedDate")),
                )
            )
        offset += len(content)
        if len(content) < 100 or offset >= data.get("totalFound", 0) or offset >= 1000 or ctx.out_of_time():
            break
    return jobs


def ashby(client, value, ctx):
    slug = board_slug(value)
    r = client.get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    r.raise_for_status()
    jobs = []
    for item in r.json().get("jobs", []):
        if item.get("isListed") is False:
            continue
        location = item.get("location") or ""
        if item.get("isRemote") or item.get("workplaceType") == "Remote":
            location = ("Remote, " + location) if location else "Remote"
        jobs.append(
            job(
                title=item.get("title"),
                company=slug,
                location=location,
                description=item.get("descriptionPlain") or plain(item.get("descriptionHtml")),
                url=clean_url(item.get("jobUrl") or item.get("applyUrl")),
                source="Ashby",
                external_id=f"{slug}:{item.get('id')}",
                posted=iso(item.get("publishedAt")),
            )
        )
    return jobs


# --- Aggregators ---------------------------------------------------------------


def remotive(client, value, ctx):
    categories = [c.strip() for c in (value or "data").split(",") if c.strip()]
    jobs = []
    for category in categories:
        r = client.get(
            "https://remotive.com/api/remote-jobs",
            params={"category": category, "limit": 100},
        )
        r.raise_for_status()
        for item in r.json().get("jobs", []):
            required = item.get("candidate_required_location") or "Worldwide"
            jobs.append(
                job(
                    title=item.get("title"),
                    company=item.get("company_name"),
                    location="Remote, " + required,
                    description=plain(item.get("description")),
                    url=clean_url(item.get("url")),
                    source="Remotive",
                    external_id=f"remotive:{item.get('id')}",
                    posted=iso(item.get("publication_date")),
                )
            )
    return jobs


RELIEFWEB_DEFAULT_QUERY = 'climate OR hydrology OR GIS OR geospatial OR "data science" OR "machine learning" OR agriculture OR "remote sensing"'


def reliefweb(client, value, ctx):
    query = (value or RELIEFWEB_DEFAULT_QUERY).strip()
    if settings.reliefweb_appname:
        return reliefweb_api(client, query, ctx)
    return reliefweb_rss(client, query, ctx)


def reliefweb_api(client, query, ctx):
    r = client.get(
        "https://api.reliefweb.int/v2/jobs",
        params={
            "appname": settings.reliefweb_appname,
            "fields[include][]": ["title", "body", "url", "date", "country", "source", "type", "how_to_apply", "city"],
            "limit": 100,
            "sort[]": "date.created:desc",
            "query[value]": query,
            "query[fields][]": ["title", "body"],
            "query[operator]": "OR",
        },
    )
    r.raise_for_status()
    jobs = []
    for item in r.json().get("data", []):
        f = item["fields"]
        types = ", ".join(t["name"] for t in f.get("type") or [])
        description = plain(f.get("body")) or f.get("body") or ""
        if f.get("how_to_apply"):
            description += "\n\nHow to apply\n" + plain(f["how_to_apply"])
        if types:
            description = f"Contract type: {types}\n\n" + description
        jobs.append(
            job(
                title=f["title"],
                company=", ".join(x["name"] for x in f.get("source") or []),
                location=", ".join(x["name"] for x in f.get("country") or []) or ("Remote" if "home-based" in description.lower() else "Not specified"),
                description=description,
                url=clean_url(f.get("url", "")),
                deadline=(f.get("date") or {}).get("closing"),
                posted=iso((f.get("date") or {}).get("created")),
                source="ReliefWeb",
                external_id=str(item["id"]),
            )
        )
    return jobs


def parse_feed(xml_bytes):
    """Minimal RSS 2.0 / Atom reader returning dicts with title, link, summary, date."""
    root = ET.fromstring(xml_bytes)
    tag = root.tag.split("}")[-1].lower()
    if tag not in ("rss", "feed", "rdf") and root.find("channel") is None:
        raise ValueError("not a feed")
    ns = {"atom": "http://www.w3.org/2005/Atom", "content": "http://purl.org/rss/1.0/modules/content/"}
    entries = []
    channel_title = ""
    if root.tag.endswith("rss") or root.find("channel") is not None:
        channel = root.find("channel")
        channel_title = (channel.findtext("title") or "").strip() if channel is not None else ""
        for item in root.iter("item"):
            entries.append(
                {
                    "title": (item.findtext("title") or "").strip(),
                    "link": (item.findtext("link") or (item.findtext("guid") or "")).strip(),
                    "summary": item.findtext("content:encoded", namespaces=ns) or item.findtext("description") or "",
                    "date": item.findtext("pubDate") or item.findtext("{http://purl.org/dc/elements/1.1/}date"),
                    "author": item.findtext("author") or item.findtext("{http://purl.org/dc/elements/1.1/}creator") or "",
                }
            )
    else:
        channel_title = (root.findtext("atom:title", namespaces=ns) or "").strip()
        for entry in root.findall("atom:entry", ns):
            link = ""
            for l in entry.findall("atom:link", ns):
                if l.get("rel") in (None, "alternate"):
                    link = l.get("href", "")
                    break
            entries.append(
                {
                    "title": (entry.findtext("atom:title", namespaces=ns) or "").strip(),
                    "link": link.strip(),
                    "summary": entry.findtext("atom:content", namespaces=ns) or entry.findtext("atom:summary", namespaces=ns) or "",
                    "date": entry.findtext("atom:published", namespaces=ns) or entry.findtext("atom:updated", namespaces=ns),
                    "author": (entry.findtext("atom:author/atom:name", namespaces=ns) or ""),
                }
            )
    return channel_title, entries


def reliefweb_rss(client, query, ctx):
    """Registration-free fallback: the public jobs feed plus each new job page."""
    r = client.get("https://reliefweb.int/jobs/rss.xml", params={"search": query})
    r.raise_for_status()
    _, entries = parse_feed(r.content)
    jobs = []
    for e in entries:
        url = clean_url(e["link"])
        if not url:
            continue
        if url in ctx.known_urls:
            jobs.append(ctx.partial(url))
            continue
        summary = BeautifulSoup(e["summary"], "html.parser")
        country = summary.select_one(".country")
        org = summary.select_one(".source")
        closing = summary.select_one(".closing")
        deadline = None
        if closing:
            m = re.search(r"(\d{1,2} \w{3} \d{4})", closing.get_text())
            if m:
                try:
                    deadline = datetime.strptime(m.group(1), "%d %b %Y").date().isoformat()
                except ValueError:
                    deadline = None
        text = ctx.fetch_page(client, url)
        if text is None:
            continue
        jobs.append(
            job(
                title=e["title"],
                company=(org.get_text().split(":", 1)[-1].strip() if org else e.get("author") or ""),
                location=(country.get_text().split(":", 1)[-1].strip() if country else ""),
                description=text,
                url=url,
                deadline=deadline,
                posted=iso(e.get("date")),
                source="ReliefWeb",
                external_id=url.rsplit("/", 2)[-2] if "/job/" in url else "",
            )
        )
    return jobs


def rss(client, value, ctx):
    """Any RSS or Atom feed of postings. Short entries are completed from the linked page."""
    feed_url = public_url(value)
    r = safe_get(client, feed_url)
    try:
        channel_title, entries = parse_feed(r.content)
    except (ET.ParseError, ValueError):
        raise ValueError("That address did not return a readable RSS or Atom feed.")
    host = urlparse(feed_url).hostname or "feed"
    jobs = []
    for e in entries:
        try:
            url = clean_url(urljoin(feed_url, e["link"]))
        except ValueError:
            continue
        if not url:
            continue
        if url in ctx.known_urls:
            jobs.append(ctx.partial(url))
            continue
        description = plain(e["summary"])
        if len(description) < 400:
            text = ctx.fetch_page(client, url)
            if text and len(text) > len(description):
                description = text
        jobs.append(
            job(
                title=e["title"] or "Untitled posting",
                company=e.get("author") or channel_title or host,
                location="",
                description=description,
                url=url,
                posted=iso(e.get("date")),
                source="RSS: " + host,
                external_id=url,
            )
        )
    return jobs


class PageListing(BaseModel):
    title: str
    url: str
    location: str = ""
    company: str = ""


class PageListings(BaseModel):
    jobs: list[PageListing]


def page(client, value, ctx):
    """A public careers page you configure. The listing is read once per run;
    an AI pass identifies postings and their links; new postings are fetched."""
    if not ai_available():
        raise ValueError("Add your OpenAI API key before using career-page sources.")
    listing_url = public_url(value)
    r = safe_get(client, listing_url)
    soup = BeautifulSoup(r.text, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        text = a.get_text(" ", strip=True)
        href = urljoin(listing_url, a["href"].strip())
        if text and href.startswith("http") and len(links) < 400:
            links.append({"text": text[:160], "href": href[:500]})
    known = {l["href"] for l in links}
    listings = structured(
        settings.extract_model,
        PageListings,
        "This is a careers/vacancies web page. Return only the individual job postings visible on it, using the exact href of each posting's link from the links list. Skip navigation, categories, news and pagination. Do not invent postings.",
        {"page_text": page_text(r.text)[:40000], "links": links},
    )
    host = urlparse(listing_url).hostname or ""
    jobs = []
    for item in listings.jobs:
        if item.url not in known:
            continue
        url = clean_url(item.url)
        if url in ctx.known_urls:
            jobs.append(ctx.partial(url))
            continue
        text = ctx.fetch_page(client, url)
        if text is None:
            continue
        jobs.append(
            job(
                title=item.title,
                company=item.company or host,
                location=item.location,
                description=text,
                url=url,
                source="Page: " + host,
                external_id=url,
            )
        )
    return jobs


# --- Gmail job alerts ------------------------------------------------------------


def get_gmail_token(client):
    if not all([settings.gmail_client_id, settings.gmail_client_secret, settings.gmail_refresh_token]):
        raise ValueError(
            "Configure Gmail OAuth client ID, secret and refresh token first (run deployment/gmail_setup.py)."
        )
    r = client.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": settings.gmail_client_id,
            "client_secret": settings.gmail_client_secret,
            "refresh_token": settings.gmail_refresh_token,
            "grant_type": "refresh_token",
        },
    )
    if r.status_code >= 400:
        raise ValueError(
            "Gmail refused the stored refresh token. Run deployment/gmail_setup.py again to reauthorize."
        )
    return r.json()["access_token"]


def extract_email_batch(items):
    """Extract several emails concurrently: items are (text, posted) tuples.
    Returns a flat list of jobs in the same order; failures raise."""
    if not items:
        return []
    # One context copy per task, taken in the calling thread so the user scope
    # travels with it; a Context cannot be entered by two threads at once.
    tasks = [(contextvars.copy_context(), text, posted) for text, posted in items]
    with ThreadPoolExecutor(max_workers=settings.evaluation_workers) as pool:
        results = list(pool.map(lambda t: t[0].run(extract_email_jobs, t[1], t[2]), tasks))
    return [job for batch in results for job in batch]


def extract_email_jobs(text, posted=None):
    """AI extraction shared by the Gmail and IMAP connectors."""
    result = structured(
        settings.extract_model,
        JobBatch,
        "Extract only job listings explicitly present in this job-alert email. Keep URLs exactly as provided. Do not invent missing descriptions, employers, locations or deadlines. Label descriptions as email excerpts when incomplete. Ignore non-job content. source must be Email alert.",
        {"email": text},
    )
    jobs = []
    for j in result.jobs:
        try:
            j.url = clean_url(j.url)
        except ValueError:
            j.url = ""
        if j.url and j.url not in text:
            j.url = ""
        jobs.append(j.model_copy(update={"source": "Email alert", "posted": posted}).model_dump())
    return jobs


def gmail(client, value, ctx):
    if (current_user() or {}).get("role") != "admin":
        raise ValueError("Gmail OAuth import is reserved for the owner account. Use the Mailbox (IMAP) source instead.")
    if not ai_available():
        raise ValueError("Add your OpenAI API key before importing job-alert emails.")
    token = get_gmail_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    r = client.get(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages",
        headers=headers,
        params={"q": value or settings.gmail_query, "maxResults": 3 if ctx.sample else 25},
    )
    r.raise_for_status()
    jobs, pending, pending_ids = [], [], []
    for msg in r.json().get("messages", []):
        if msg["id"] in ctx.seen_mail:
            continue
        if ctx.out_of_time():
            break
        response = client.get(
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg['id']}",
            headers=headers,
        )
        response.raise_for_status()
        message = response.json()
        payload = message.get("payload", {})

        def text_parts(part):
            chunks = []
            if part.get("mimeType") in ("text/plain", "text/html") and part.get("body", {}).get("data"):
                raw = base64.urlsafe_b64decode(part["body"]["data"] + "===").decode("utf-8", errors="replace")
                chunks.append(plain(raw) if part["mimeType"] == "text/html" else raw)
            for child in part.get("parts", []):
                chunks.extend(text_parts(child))
            return chunks

        text = "\n".join(text_parts(payload))[:60000]
        pending.append((text, iso(int(message.get("internalDate", 0) or 0))))
        pending_ids.append(msg["id"])
    jobs.extend(extract_email_batch(pending))
    ctx.mail_ids.extend(pending_ids)
    return jobs


IMAP_TIMEOUT = 30


def public_host(host):
    """Same destination policy as public_url, for non-HTTP hosts. Returns one
    validated public address to connect to."""
    host = (host or "").strip().lower()
    if not host or host in ("localhost",) or host.endswith((".localhost", ".local", ".internal")):
        raise ValueError("Local or private addresses cannot be used.")
    try:
        candidates = [host] if ipaddress.ip_address(host) else []
    except ValueError:
        candidates = resolve_host(host)
    for address in candidates:
        ip = ipaddress.ip_address(address.split("%")[0])
        if not ip.is_global or ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            raise ValueError("That mailbox address points to a private or local network and cannot be used.")
    return candidates[0]


def imap_connect(host, port, timeout=IMAP_TIMEOUT):
    """TLS IMAP connection to a validated public address, keeping the hostname
    for certificate verification, so DNS cannot redirect it after the check."""
    address = public_host(host)

    def _create_socket(self, timeout_):
        sock = socket.create_connection((address, self.port), timeout_)
        return self.ssl_context.wrap_socket(sock, server_hostname=self.host)

    pinned = type("PinnedIMAP4_SSL", (imaplib.IMAP4_SSL,), {"_create_socket": _create_socket})
    return pinned(host, int(port or 993), timeout=timeout)


def _imap_quote(folder):
    return '"' + folder.replace("\\", "\\\\").replace('"', '\\"') + '"'



LEGACY_FOLDER = "CareerPilot"  # label name from before the rename; still honoured


def _select_folder(box, folder):
    """Select a mailbox folder read-only; a missing default folder falls back to the legacy label."""
    status, data = box.select(_imap_quote(folder), readonly=True)
    if status != "OK" and folder == "JobsFindAI":
        status, data = box.select(_imap_quote(LEGACY_FOLDER), readonly=True)
    return status, data

def imap_mailbox(client, value, ctx):
    """Job-alert emails read from the user's own mailbox with an app password
    (Gmail, Outlook, Yahoo, Fastmail…). Reads one label/folder, newest first."""
    creds = (current_user() or {}).get("imap") or {}
    if not creds.get("host") or not creds.get("username") or not creds.get("password"):
        raise ValueError("Add your mailbox (IMAP) details under Account first.")
    if not ai_available():
        raise ValueError("Add your OpenAI API key before importing job-alert emails.")
    folder = (value or creds.get("folder") or "JobsFindAI").strip()
    since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%d-%b-%Y")
    jobs, pending = [], []
    with imap_connect(creds["host"], creds.get("port")) as box:
        try:
            box.login(creds["username"], creds["password"])
        except imaplib.IMAP4.error:
            raise ValueError("The mailbox refused the login. For Gmail use an app password, not your normal password.")
        status, _ = _select_folder(box, folder)
        if status != "OK":
            raise ValueError(f"The folder or label '{folder}' was not found in the mailbox.")
        status, data = box.uid("search", None, f"(SINCE {since})")
        uids = data[0].split() if status == "OK" and data and data[0] else []
        limit = 3 if ctx.sample else 25
        for uid in reversed(uids[-60:]):
            uid = uid.decode()
            key = f"imap:{creds['username']}:{folder}:{uid}"
            if key in ctx.seen_mail:
                continue
            if len(ctx.mail_ids) >= limit or ctx.out_of_time():
                break
            status, parts = box.uid("fetch", uid, "(RFC822)")
            if status != "OK" or not parts or not isinstance(parts[0], tuple):
                continue
            message = email.message_from_bytes(parts[0][1], policy=email.policy.default)
            chunks = []
            for part in message.walk():
                ctype = part.get_content_type()
                if ctype in ("text/plain", "text/html"):
                    try:
                        body = part.get_content()
                    except Exception:
                        continue
                    chunks.append(plain(body) if ctype == "text/html" else body)
            text = ("\n".join(chunks))[:60000]
            if len(text.strip()) < 40:
                ctx.mail_ids.append(key)
                continue
            posted = iso(message.get("Date")) if message.get("Date") else None
            pending.append((text, posted))
            ctx.mail_ids.append(key)
    jobs.extend(extract_email_batch(pending))
    return jobs


def imap_check(creds):
    """Verify mailbox credentials and folder without reading any message."""
    with imap_connect(creds["host"], creds.get("port")) as box:
        try:
            box.login(creds["username"], creds["password"])
        except imaplib.IMAP4.error:
            raise ValueError("The mailbox refused the login. For Gmail use an app password, not your normal password.")
        status, data = _select_folder(box, creds.get("folder") or "JobsFindAI")
        if status != "OK":
            raise ValueError("Logged in, but the folder or label was not found. Create it in your mailbox first.")
        return int(data[0] or 0)


CONNECTORS = {
    "greenhouse": greenhouse,
    "lever": lever,
    "workable": workable,
    "smartrecruiters": smartrecruiters,
    "ashby": ashby,
    "remotive": remotive,
    "reliefweb": reliefweb,
    "rss": rss,
    "page": page,
    "gmail": gmail,
    "imap": imap_mailbox,
}

KIND_LABELS = {
    "reliefweb": "ReliefWeb jobs",
    "imap": "Mailbox alerts via IMAP (LinkedIn, Devex, UNjobs…)",
    "gmail": "Gmail OAuth alerts (owner account)",
    "rss": "RSS / Atom feed",
    "page": "Careers page (AI-read)",
    "greenhouse": "Greenhouse employer board",
    "lever": "Lever employer board",
    "workable": "Workable employer board",
    "smartrecruiters": "SmartRecruiters employer board",
    "ashby": "Ashby employer board",
    "remotive": "Remotive remote jobs",
}

SUGGESTED_SOURCES = [
    {
        "kind": "reliefweb",
        "value": RELIEFWEB_DEFAULT_QUERY,
        "label": "ReliefWeb: climate, data, GIS, agriculture",
        "note": "Development-sector jobs and consultancies worldwide.",
    },
    {
        "kind": "reliefweb",
        "value": "Ethiopia",
        "label": "ReliefWeb: postings mentioning Ethiopia",
        "note": "Catches Ethiopia-based roles in any field; the keyword screen keeps the relevant ones.",
    },
    {
        "kind": "remotive",
        "value": "data,artificial-intelligence,research",
        "label": "Remotive: remote data, AI and research roles",
        "note": "Remote roles; check each posting's eligible regions.",
    },
    {
        "kind": "workable",
        "value": "cgiar",
        "label": "CGIAR (Workable board)",
        "note": "CGIAR system-level postings.",
    },
    {
        "kind": "imap",
        "value": "",
        "label": "Your mailbox: label JobsFindAI",
        "note": "Route LinkedIn, Devex, UNjobs, Impactpool or ReliefWeb email alerts to a JobsFindAI label, then connect the mailbox under Account.",
    },
]


def validate_source(kind, value):
    """Raise ValueError when a source value is malformed for its kind."""
    if kind in ("greenhouse", "lever", "workable", "smartrecruiters", "ashby"):
        board_slug(value)
    elif kind in ("rss", "page"):
        public_url(value)
    elif kind == "imap":
        if not (current_user() or {}).get("imap"):
            raise ValueError("Add your mailbox (IMAP) details under Account before using this source.")
    elif kind == "remotive":
        if not re.fullmatch(r"[a-z0-9,-]*", value or ""):
            raise ValueError("Remotive categories are lowercase slugs separated by commas, for example data,research.")


def collect(source, seen_mail=None, ctx=None):
    """Run one source. Returns (jobs, message_ids). Jobs may include partial
    entries {url, partial: True} for postings already stored."""
    kind, value = source["kind"], (source.get("value") or "").strip()
    if kind not in CONNECTORS:
        raise ValueError(f"Unknown source kind: {kind}")
    ctx = ctx or Context(seen_mail=seen_mail)
    if seen_mail and not ctx.seen_mail:
        ctx.seen_mail = set(seen_mail)
    validate_source(kind, value)
    attempts = 0
    while True:
        attempts += 1
        try:
            with httpx.Client(
                timeout=httpx.Timeout(60, connect=20),
                follow_redirects=False,
                headers={"User-Agent": USER_AGENT},
            ) as client:
                jobs = CONNECTORS[kind](client, value, ctx)
            return jobs, list(ctx.mail_ids)
        except httpx.TransportError as e:
            # Dropped connections and chunked-read failures are usually transient.
            if attempts >= 3:
                raise ValueError(
                    f"The provider closed the connection ({type(e).__name__}). It will be retried on the next search."
                )
            log.warning("Transient error reading %s (%s); retrying", kind, type(e).__name__)
            time.sleep(2 * attempts)
