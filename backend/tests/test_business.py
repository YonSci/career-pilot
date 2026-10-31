"""Business report: revenue by month and product, checkout conversion, members, employers."""

from career.config import settings
from career import business_report
from tests.conftest import signup_member
from tests.test_employers import mailbox, submit, link_in, sign_in


def test_business_report_counts_revenue_members_and_employers(client, monkeypatch, capsys):
    sent = mailbox(monkeypatch)
    member = signup_member(client)
    # A member buys Pro by hand (no gateway configured), and starts a second checkout they never pay.
    ref = member.post("/api/billing/checkout", json={"product": "pro", "currency": "ETB"}).json()["ref"]
    client.post(f"/api/admin/payments/{ref}/paid")
    member.post("/api/billing/checkout", json={"product": "package", "currency": "USD"})
    # An employer pays for a featured listing; another submission is still under review.
    post_id = submit(sent)
    submit(sent, title="Rangeland Ecologist")
    client.put(f"/api/admin/employer-posts/{post_id}", json={"status": "approved"})
    employer = sign_in(link_in(sent[-1]))
    employer.post(f"/employers/listings/{post_id}/checkout", data={"currency": "USD"})
    listing_ref = next(p["ref"] for p in client.get("/api/admin/overview").json()["payments"] if p.get("post_id") == post_id)
    client.post(f"/api/admin/payments/{listing_ref}/paid")

    r = client.get("/api/admin/business").json()
    assert r["all_time"] == {"ETB": settings.price_pro_etb, "USD": settings.featured_listing_usd, "count": 2}
    assert r["revenue"][-1]["month"] == r["month"] and r["revenue"][-1]["count"] == 2 and len(r["revenue"]) == 6
    assert r["products"]["pro"]["ETB"] == settings.price_pro_etb and r["products"]["featured_listing"]["USD"] == settings.featured_listing_usd
    assert r["checkouts"]["manual"] == {"started": 3, "paid": 2}
    assert r["awaiting_confirmation"] == {"count": 1, "ETB": 0, "USD": settings.price_package_usd}
    assert r["members"]["paying_now"] == 1 and r["members"]["ever_paid"] == 1 and r["members"]["new_payers_this_month"] == 1
    assert r["employers"]["submitted"] == 2 and r["employers"]["approved"] == 1 and r["employers"]["paid"] == 1
    assert r["employers"]["median_days_approval_to_payment"] is not None
    # Owner only.
    assert member.get("/api/admin/business").status_code == 403

    business_report.main()
    out = capsys.readouterr().out
    assert f"Revenue all time: {settings.price_pro_etb:,} ETB + {settings.featured_listing_usd:,} USD from 2 payments" in out
    assert "Employers: submitted 2 -> approved 1 -> paid 1" in out and "manual 2/3 (67%)" in out
