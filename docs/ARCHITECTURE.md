# Jobs Find AI architecture

This is a personal-use application. The Python API owns all private data. A bearer access token protects every data endpoint. The hosted dashboard is owner-private and can proxy to a separately hosted Python API using an explicit owner email allowlist. The portable dashboard uses the same React component and can be served by FastAPI.

## Runtime

- Python 3.12, FastAPI, SQLAlchemy; SQLite for local manual use, PostgreSQL in Docker Compose.
- LangGraph runs the evidence gate and drafting workflow. Approval, preparation status, profile/job snapshots, and draft history persist in SQL. This first release uses application-level persisted state, not a LangGraph checkpointer.
- OpenAI Responses structured outputs extract a profile, evaluate requirements, draft a package, and independently review factual support.
- Celery + Redis process background work in Docker, where Celery Beat runs searches every six hours. In the local mode (`TASK_QUEUE=background`) an in-process scheduler thread starts searches at the interval set in Preferences and a second thread long-polls Telegram; both stop with the server. Stale runs and preparations are repaired at startup.
- Connectors: ReliefWeb (API v2 with appname, RSS fallback otherwise), Gmail job-alert ingestion, generic RSS/Atom, AI-read careers pages, Greenhouse, Lever, Workable, SmartRecruiters, Ashby and Remotive. Page-reading connectors fetch only configured public pages, capped per run with a delay, and skip URLs already stored. LinkedIn collection uses email alerts; no website login or scraping.
- In-app inbox (always), SMTP with STARTTLS, Telegram Bot API (long polling locally, webhook on HTTPS) with in-app chat linking, Twilio approved WhatsApp templates. Per-job or digest mode.
- Single-column DOCX and PDF exports, evidence references, screening answers, extra narrative documents, and a checklist in one ZIP.

## Storage

The records table stores typed JSON documents with unique natural keys and timestamps: profile, profile_source, preferences, schedule, source, job, body (description-hash index for cross-post detection), application, application_version, run, alert (including in-app inbox entries), mail, telegram, telegram_link, telegram_offset. The initial schema is created through SQLAlchemy. Add explicit migration tooling before evolving the production schema. The first release intentionally does not need embeddings or a vector database for one person's evidence bank.

Application versions include snapshots. Edited drafts never update master profile facts. Job scores are invalidated only when verified evidence or the keyword/location/contract preferences change. Cross-post deduplication is conservative: canonical URL or identical employer/title/location/description. Similar-but-not-identical postings remain separate.

## Workflow and limits

1. Extract CV statements and exact supporting source excerpts. Every fact starts unverified.
2. User corrects and verifies evidence. Only verified facts reach matching and writing.
3. Collect jobs from configured sources, screen by word stem against keywords (and optionally strictly by location), normalize and deduplicate. Evaluate the most promising unevaluated postings first: title matches, preferred locations, newest.
4. Separate mandatory eligibility (met / not_met / unknown) from relevance score. Unknown evidence is never treated as a known qualification.
5. Notify only AI-reviewed matches meeting the configured threshold and without known mandatory disqualifiers. Alert content includes gaps/unknowns.
6. A deliberate Prepare action records approval and queues drafting. No submission API exists.
7. Check factual references, response limits, and an independent AI review; one automatic revision pass addresses reviewer objections before a draft is rejected. User edits and exports.

Costs are bounded by 50 fresh match evaluations per run by default (failed evaluations retry three times then pause for a day), 10 alert jobs per run by default, 60 page fetches per run, feed pagination limits, deduplicated email IDs, descriptions trimmed to 30,000 characters for analysis, and drafting only after approval. Postings unseen in any feed for 45 days and never shortlisted are archived. These are operational limits, not guarantees of complete job-board coverage.

## Reliability

Provider delivery is not exactly-once. A unique alert record is committed before sending. A timeout after possible acceptance becomes delivery_unknown and is never automatically resent. Accepted means accepted by the provider, not confirmed delivery. Operators should reconcile unknown deliveries before any manual retry.

Application preparation is claimed with compare-and-swap; duplicate requests reuse existing drafts. Interrupted preparations may be explicitly retried after ten minutes. Docker uses a durable Redis queue; simple local background tasks require manual retry after a process interruption. Run only one scheduler.

## Boundaries

- Original source links and last-seen times are retained. Missing/ambiguous deadlines remain unknown. Date-only deadlines are treated as open through that calendar date; exact employer cutoff/timezone needs review.
- The app does not claim a vacancy is still open merely because its stored deadline is in the future. Verify on the employer site before submission.
- Gmail ingestion checks up to 25 recent labeled emails per run; ReliefWeb checks up to 100 results; Lever pagination is capped at 5,000 postings per employer.
- The UI does not automate employer portals or submit applications. It cannot sign forms, create certificates, supply real references, or invent financial rates.
- Scanned CVs need OCR first. DOCX/PDF layouts need human review for the actual content. Some specialized Unicode scripts may require a custom PDF font.
- All users sharing a backend access token share the same personal workspace. This is not a multi-user SaaS implementation.
- Automatic follow-up reminders and learned ranking are later extensions. Page reading is limited to feeds and pages you configure; there is no crawling beyond the linked postings.

## Validation

Automated checks exercise auth, CV review, safe URLs, deadlines, deduplication, persistence, approval-gated preparation, exported DOCX/PDF content, response limits, retry protection, and Telegram identity checks. Providers are mocked for deterministic integration tests. Live model quality, real delivery, Gmail/WhatsApp onboarding, container startup and browser interactions require a configured deployment.
