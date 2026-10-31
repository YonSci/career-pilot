"""Public-site measurement without cookies or third parties: daily counts of page
views by page type, arrivals from search engines, and clicks to apply or to see
how a member matches. Crawlers are not counted. Nothing identifies a visitor:
only the referring search engine's name is kept, never the page or query."""

import re
import threading
from collections import Counter
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse
from .db import SYSTEM, read, put

ENGINES = {
    "google": re.compile(r"(^|\.)google\.[a-z.]+$"),
    "bing": re.compile(r"(^|\.)bing\.com$"),
    "duckduckgo": re.compile(r"(^|\.)duckduckgo\.com$"),
    "yahoo": re.compile(r"(^|\.)yahoo\.[a-z.]+$"),
    "yandex": re.compile(r"(^|\.)yandex\.[a-z.]+$"),
    "baidu": re.compile(r"(^|\.)baidu\.com$"),
    "ecosia": re.compile(r"(^|\.)ecosia\.org$"),
    "brave": re.compile(r"^search\.brave\.com$"),
}
BOTS = re.compile(r"bot|crawl|spider|slurp|preview|facebookexternalhit|embedly|curl|wget|python|headless|lighthouse", re.I)
_lock = threading.Lock()


def is_bot(user_agent):
    return not user_agent or bool(BOTS.search(user_agent))


def engine(referer):
    host = (urlparse(referer or "").hostname or "").lower()
    return next((name for name, pattern in ENGINES.items() if pattern.search(host)), None)


def _key(day):
    return "site-stats:" + day


def record(db, page, request, event="view"):
    """Count a page view (with its search engine, if any) or a click ("apply", "match")."""
    if is_bot(request.headers.get("user-agent")):
        return
    day = datetime.now(timezone.utc).date().isoformat()
    with _lock:
        data = read(db, _key(day), {}, user_id=SYSTEM) or {}
        if event == "view":
            data["views"] = {**data.get("views", {}), page: data.get("views", {}).get(page, 0) + 1}
            found = engine(request.headers.get("referer"))
            if found:
                data["search"] = {**data.get("search", {}), page: data.get("search", {}).get(page, 0) + 1}
                data["engines"] = {**data.get("engines", {}), found: data.get("engines", {}).get(found, 0) + 1}
        else:
            data[event] = {**data.get(event, {}), page: data.get(event, {}).get(page, 0) + 1}
        put(db, "site-stats", _key(day), data, user_id=SYSTEM)


def summary(db, days=30):
    """Totals over the last `days` days."""
    today = datetime.now(timezone.utc).date()
    totals = {k: Counter() for k in ("views", "search", "engines", "apply", "match")}
    for n in range(days):
        data = read(db, _key((today - timedelta(days=n)).isoformat()), {}, user_id=SYSTEM) or {}
        for k in totals:
            totals[k].update(data.get(k, {}))
    job_views = totals["views"]["job"]
    clicks = sum(totals["apply"].values()) + sum(totals["match"].values())
    return {
        "days": days,
        **{k: dict(v.most_common()) for k, v in totals.items()},
        "page_views": sum(totals["views"].values()),
        "search_arrivals": sum(totals["search"].values()),
        "job_page_click_through": round(clicks / job_views, 3) if job_views else None,
    }
