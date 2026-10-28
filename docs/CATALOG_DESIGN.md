# Shared job catalog: design

Status: phases 1 (shadow catalog), 2 (starter results) and 4 (keyword-rejected sample) implemented, 29 October 2026. Phase 3 is a proposal.

Phase 2 as built: "recent" means seen in a source's fetch within the last 7 days (`STARTER_DAYS`) and not past its deadline, an approximation of the retention decision below. Postings the member already has a job for, including skipped ones, are never offered again. Keyword-rejected postings are screened again on each search; nothing is stored for them.

Phase 4 as built: the sample is drawn from each search's own keyword rejections (catalog and private sources alike), one per search and `KEYWORD_SAMPLE_PER_MONTH` per member, and is LLM-evaluated ahead of JEV so the comparison does not depend on JEV. JEV scoring of the sample is left out; `jev_report` keeps it out of the JEV comparison.

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

## Decisions for the owner (recommended answers, 29 October 2026)

- **Which sources feed the catalog:** an allowlist by source type. Member-added ReliefWeb searches and employer boards (Greenhouse, Lever, Ashby, Workable, SmartRecruiters) feed it automatically. Remotive, careers pages and RSS feeds stay private to the member who added them unless the owner approves a specific site. Mailbox and manual postings are always private.
- **Retention:** a posting stays a candidate until its deadline passes or it is missing from 7 days of successful fetches of its source. Employer boards and ReliefWeb list every open posting, so absence usually means closed. Catalog text is deleted after 90 days unless a member has a job for it. Members' own jobs keep the 45-day archive.
- **Freshness before alerts:** no extra fetch. Only alert on postings present in their source's most recent successful fetch.
- **Source terms** (from each provider's own documentation; not legal advice):
  - Remotive forbids passing its jobs to third-party sites, Google Jobs included, and using them to collect signups. It is excluded from the catalog and, since 29 October 2026, from the public job pages, channel and structured data (`PRIVATE_SOURCES` in `career/public_jobs.py`).
  - ReliefWeb: anyone may use the API with a pre-approved `appname`. Respect the original organisation's rights: show it as the source and link to the posting.
  - Greenhouse and Lever job board data is public and needs no key; Lever notes published postings "may be scraped by third parties". Neither states aggregator terms. Show an excerpt, link to the employer's page, and remove a posting if an employer asks.

## Not in scope

Large commercial job feeds. A catalog of millions of postings needs licensing and different infrastructure. Start with the sources members already use and measure whether coverage is the bottleneck.
