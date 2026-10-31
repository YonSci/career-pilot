"""Business report: revenue, checkout conversion, paying members, the employer
funnel, institution enquiries and the AI usage the revenue has to cover.

    python -m career.business_report     (on Render: Shell tab, from /app)

The same figures appear in the Cohort tab. ETB and USD are kept apart: no
exchange rate is assumed. Read-only."""

from collections import Counter
from datetime import datetime, timezone
from statistics import median
from .db import SYSTEM, User, read
from .config import settings
from . import billing, growth, employers

MONTHS = 6
PAID_PLANS = ("pro", "pro_plus")


def _month(stamp):
    return (stamp or "")[:7]


def _months(n=MONTHS):
    """The last n months, oldest first, as YYYY-MM."""
    now = datetime.now(timezone.utc)
    y, m, out = now.year, now.month, []
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    return out[::-1]


def _days(a, b):
    try:
        return (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() / 86400
    except (TypeError, ValueError):
        return None


def _sum(items):
    """{"ETB": total, "USD": total, "count": n} for paid payments."""
    out = {"ETB": 0, "USD": 0, "count": 0}
    for p in items:
        out[p["currency"]] = out.get(p["currency"], 0) + (p.get("amount") or 0)
        out["count"] += 1
    return out


def report(db):
    months = _months()
    this_month = months[-1]
    payments = billing.payments(db)
    paid = [p for p in payments if p.get("status") == "paid"]

    revenue = [{"month": m, **_sum(p for p in paid if _month(p.get("paid_at")) == m)} for m in months]
    products = {
        product: {"label": billing.PRODUCTS.get(product, {}).get("label", product), **_sum(p for p in paid if p["product"] == product)}
        for product in sorted({p["product"] for p in paid})
    }
    # Checkouts started per provider and how many were paid. Manual requests count as started.
    checkouts = {}
    for provider in sorted({p.get("provider") or "?" for p in payments}):
        started = [p for p in payments if (p.get("provider") or "?") == provider]
        done = sum(1 for p in started if p.get("status") == "paid")
        checkouts[provider] = {"started": len(started), "paid": done}
    waiting = [p for p in payments if p.get("provider") == "manual" and p.get("status") == "requested"]

    users = db.query(User).all()
    plans = Counter(u.plan for u in users)
    now = datetime.now(timezone.utc).isoformat()
    paying = [u for u in users if u.plan in PAID_PLANS and (u.settings or {}).get("plan_until", "") > now]
    member_paid = [p for p in paid if p.get("user_id")]
    first_paid = {}
    for p in sorted(member_paid, key=lambda p: p.get("paid_at") or ""):
        first_paid.setdefault(p["user_id"], p.get("paid_at") or "")
    per_payer = Counter(p["user_id"] for p in member_paid if billing.PRODUCTS.get(p["product"], {}).get("plan"))

    posts = growth.employer_posts(db)
    states = Counter(employers.state(p) for p in posts)
    listing_paid = [p for p in paid if p["product"] == "featured_listing"]
    paid_posts = {p.get("post_id") for p in listing_paid}
    to_payment = []
    for post in posts:
        payment = min((p for p in listing_paid if p.get("post_id") == post["id"]), key=lambda p: p.get("paid_at") or "", default=None)
        wait = _days(post.get("moderated"), payment.get("paid_at")) if payment else None
        if wait is not None:
            to_payment.append(wait)
    stats = [employers.stats(db, p["id"]) for p in posts]
    views, clicks = sum(s["views"] for s in stats), sum(s["apply_clicks"] for s in stats)

    enquiries = growth.enquiries(db)
    usage = {m: (read(db, "usage:" + m, {}, user_id=SYSTEM) or {}).get("calls", 0) for m in months}
    jev_tokens = {m: (read(db, "jev-usage:" + m, {}, user_id=SYSTEM) or {}).get("tokens", 0) for m in months}

    return {
        "month": this_month,
        "revenue": revenue,
        "all_time": _sum(paid),
        "products": products,
        "checkouts": checkouts,
        "awaiting_confirmation": {"count": len(waiting), **{c: sum(p["amount"] for p in waiting if p["currency"] == c) for c in ("ETB", "USD")}},
        "members": {
            "accounts": len(users),
            "plans": dict(plans),
            "paying_now": len(paying),
            "new_payers_this_month": sum(1 for at in first_paid.values() if _month(at) == this_month),
            "repeat_payers": sum(1 for n in per_payer.values() if n > 1),
            "ever_paid": len(first_paid),
            "unused_credits": sum(int((u.settings or {}).get("credits") or 0) for u in users),
        },
        "employers": {
            "submitted": len(posts),
            "approved": sum(1 for p in posts if p.get("status") == "approved"),
            "paid": len(paid_posts & {p["id"] for p in posts}),
            "states": dict(states),
            "median_days_approval_to_payment": round(median(to_payment), 1) if to_payment else None,
            "views": views,
            "apply_clicks": clicks,
            "matches": sum(s["matches"] for s in stats),
            "click_through": round(clicks / views, 3) if views else None,
        },
        "institutions": {
            "enquiries": len(enquiries),
            "seats_asked": sum(e.get("seats") or 0 for e in enquiries),
            "new": sum(1 for e in enquiries if e.get("status") == "new"),
        },
        "ai_usage": [{"month": m, "server_key_calls": usage[m], "jev_tokens": jev_tokens[m]} for m in months],
        "caps": {"server_key_monthly_calls": settings.server_key_monthly_calls, "jev_monthly_tokens": settings.jev_monthly_tokens},
    }


def _money(s):
    parts = [f"{s[c]:,} {c}" for c in ("ETB", "USD") if s.get(c)]
    return " + ".join(parts) or "0"


def _share(n, d):
    return f"{n}/{d} ({n / d:.0%})" if d else f"{n}/0"


def print_report(r):
    print(f"Business report, {r['month']} (ETB and USD kept apart; no exchange rate assumed)")
    print(f"Revenue all time: {_money(r['all_time'])} from {r['all_time']['count']} payments")
    print("Revenue by month (paid date):")
    for m in r["revenue"]:
        print(f"  {m['month']}: {_money(m)} ({m['count']} payments)")
    print("By product: " + ("; ".join(f"{p['label']} {_money(p)} ({p['count']})" for p in r["products"].values()) or "none yet"))
    print("Checkouts started -> paid: " + ("; ".join(f"{k} {_share(v['paid'], v['started'])}" for k, v in r["checkouts"].items()) or "none yet"))
    w = r["awaiting_confirmation"]
    if w["count"]:
        print(f"  Manual requests awaiting confirmation in the Cohort tab: {w['count']} ({_money(w)})")
    m = r["members"]
    print(f"Members: {m['accounts']} accounts; plans " + ", ".join(f"{k} {v}" for k, v in sorted(m["plans"].items())))
    print(f"  paying now {_share(m['paying_now'], m['accounts'])}; ever paid {m['ever_paid']}; new payers this month {m['new_payers_this_month']}; "
          f"bought a plan more than once {m['repeat_payers']}; unused package credits {m['unused_credits']}")
    e = r["employers"]
    print(f"Employers: submitted {e['submitted']} -> approved {e['approved']} -> paid {e['paid']}; now " + ", ".join(f"{k} {v}" for k, v in sorted(e["states"].items())))
    if e["median_days_approval_to_payment"] is not None:
        print(f"  median days from approval to payment: {e['median_days_approval_to_payment']}")
    ctr = f"{e['click_through']:.0%}" if e["click_through"] is not None else "n/a"
    print(f"  featured listings: {e['views']} page views, {e['apply_clicks']} Apply clicks (click-through {ctr}), {e['matches']} member matches")
    i = r["institutions"]
    print(f"Institutions: {i['enquiries']} enquiries ({i['new']} new) asking for {i['seats_asked']} seats")
    print(f"AI usage the revenue covers (caps: {r['caps']['server_key_monthly_calls']:,} server-key calls, {r['caps']['jev_monthly_tokens']:,} JEV tokens a month):")
    for u in r["ai_usage"]:
        print(f"  {u['month']}: {u['server_key_calls']:,} server-key calls, {u['jev_tokens']:,} JEV input tokens")
