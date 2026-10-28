# Shared job catalog: design

Status: proposal, not implemented. Written 29 October 2026.

## Problem

Every member collects postings from their own sources into their own records. That has three costs:

- **Onboarding.** A new member sees nothing until they configure sources and keywords. Members who don't know which boards to add get a thin feed.
- **Duplicate work.** Twenty members with the same ReliefWeb or Greenhouse source fetch and store the same postings twenty times, each within the per-search page limit.
- **Blind spots.** Keyword screening discards postings before they are stored, so neither JEV nor the report can check whether a member's keywords miss good jobs.

`career/public_jobs.py` already combines public postings from all members for the landing page, with the same privacy rule this design needs: public facts only, nothing about who collected a posting or what anyone did with it, and email-alert and manual postings never included.

## Proposal

Split each posting into a shared **catalog posting** and a private **member job**.

| | Catalog posting | Member job |
|---|---|---|
| Owner | `SYSTEM` | The member |
| Holds | Title, employer, location, description, URL, dates, source, `first_seen`, `last_seen` | Status and stage history, LLM match, JEV score, alerts |
| Comes from | Public sources only: ReliefWeb, ATS boards (Greenhouse, Lever, Workable, SmartRecruiters, Ashby), RSS, Remotive, careers pages | Created when a catalog posting enters the member's candidate pool, or from the member's private sources (mailbox alerts, manual entries) as today |
| Visible to | Every member, as a candidate | That member only |

A member job keeps a reference to its catalog posting (`posting_key`), so an updated description or deadline in the catalog clears that member's stale match, as `ingest` does today.

### Collection

- The scheduler collects every **distinct** public source once per cycle, instead of once per member. The source list is the owner's curated list plus the union of members' public sources.
- Each catalog posting stores where it came from, not who added the source. A member's source list can reveal their interests, so it stays private.
- Deduplication reuses `fingerprint` (cleaned URL) and the body-hash cross-post check, now across all members.
- Politeness limits (`MAX_PAGE_FETCHES_PER_RUN`, `FETCH_DELAY_SECONDS`) apply to the shared collector as a whole.

### Matching

For each member's search:

1. Candidate pool: catalog postings seen in the last `N` days that the member has no job for yet, plus their private-source postings.
2. Keyword screen, then JEV, then the LLM within the member's budget, as today.
3. A member job is created only when a posting passes the screen, so members don't get thousands of records.
4. **Keyword-rejected sample:** because the catalog keeps every posting, a small random sample of postings the screen rejects can be JEV-scored and occasionally LLM-evaluated. That shows whether keywords miss good jobs, the gap the JEV review raised.

### Onboarding

A new member with a verified CV gets "Suggest from my CV" keywords and locations, then results straight away from the catalog without adding any source. Their own sources stay available for specialised monitoring.

## Data model

SQLite stays. Catalog postings use the existing `records` table with `user_id = SYSTEM` and `kind = "posting"`. Member jobs keep `kind = "job"` and gain `posting_key`. At the current scale (about 1,400 postings) no new table is needed. A separate table with indexes on `last_seen` and `fingerprint` becomes worthwhile past roughly 50,000 postings.

## Rollout

1. **Shadow catalog.** The current per-member ingest also writes catalog postings. Nothing reads them yet. Measure coverage, duplicates and freshness.
2. **Starter results.** Members with no sources get catalog candidates. Everyone else is unchanged.
3. **Subscriptions.** Members' public sources become subscriptions to the shared collector, and per-member fetching of public sources stops.
4. **Keyword-rejected sample** and its line in `jev_report`.

Each phase can be released and reverted on its own. Phase 1 is about two days of work; the full rollout is about one to two weeks.

## Decisions for the owner

- **Which sources feed the catalog:** only an owner-curated list, or also every public source a member adds? The second gives more coverage and reveals nothing about the member, but lets any member add load.
- **Retention:** how long a posting not seen in any feed stays a candidate. Today it's 45 days to archive.
- **Freshness checks:** whether to re-check that a posting is still open before alerting. That costs one fetch per alert.
- **Source terms:** confirm that each board's terms allow storing postings centrally and showing them to members. ReliefWeb needs an `appname`; ATS board APIs are public.

## Not in scope

Large commercial job feeds. A catalog of millions of postings needs licensing and different infrastructure. Start with the sources members already use and measure whether coverage is the bottleneck.
