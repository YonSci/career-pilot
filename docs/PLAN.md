# Jobs Find AI: review and plan to make it fully functional

Reviewed 2026-09-19 against the code, the test suite, the live SQLite database and live probes of the external APIs.

## 1. How the system is meant to work

1. **Evidence.** You upload a CV. AI extracts facts with exact source quotes. You verify each fact. Only verified facts are ever used for matching or writing.
2. **Discovery.** On a schedule, every enabled source is polled. Postings are normalised, de-duplicated (canonical URL or identical body), pre-filtered by your keywords, then evaluated by AI (bounded to 50 per run).
3. **Explanation.** Each evaluated job stores a 0-100 relevance score, a summary, a requirement-by-requirement table (met / unknown / not_met with evidence IDs), strengths and gaps.
4. **Alerting.** Jobs at or above your threshold with no mandatory `not_met` trigger one alert per job per channel (Telegram, email, WhatsApp). Alerts are never resent.
5. **Action.** From Telegram you mark Interested / Skip. In the dashboard you click **Prepare application**; a LangGraph workflow checks the evidence gate, drafts CV, cover letter, screening answers and extra documents grounded in evidence IDs, then an independent AI review rejects unsupported claims. You edit, mark ready and export a ZIP (DOCX + PDF + checklist).

## 2. What is verified working today

| Area | Status | Evidence |
|---|---|---|
| Backend tests | Pass | 21/21 on the project's Python 3.11 venv |
| OpenAI connection | Working | Key valid; `gpt-5.6-luna`, `gpt-5.6-terra`, `gpt-5.6-sol` all resolve |
| CV import and verification | Working | Profile has 33 AI-categorised facts, all verified |
| Local server | Running | `uvicorn career.main:app` on 127.0.0.1:8000, SQLite, `TASK_QUEUE=background` |
| Preferences saved | Yes | Keywords, Ethiopia/Remote, alerts on, all 3 channels ticked, schedule on |
| Manual add → evaluate → prepare → export | Untested live | Covered by mocked tests; never exercised with a real job because no job exists |

## 3. What is broken or missing

The database shows 13 search runs and **zero jobs ever collected**. The root causes:

### A. Discovery cannot produce jobs
1. **ReliefWeb connector is dead.** It calls API v1, which now returns `410 decommissioned`. v2 exists but requires an approved appname requested through a Google form. Every run you made failed on this source; the last run has no sources at all.
2. **Only Greenhouse and Lever employer boards remain.** You must know each employer's slug, and most development-sector employers (UN agencies, CGIAR centres, FAO, WFP, World Bank) are not on these platforms.
3. **Gmail alerts are unusable in practice.** The connector needs an OAuth refresh token, but there is no helper to obtain one. Gmail is the most valuable source because LinkedIn, ReliefWeb email alerts, UNjobs, Devex, Impactpool and Indeed all deliver by email.
4. **Keyword pre-filter drops relevant jobs.** It requires the exact phrase. "data science" does not match "Data Scientist"; "digital agriculture" does not match "agricultural data". Relevant postings are silently discarded before AI ever sees them.

### B. Nothing runs continuously
5. The **Scheduled searches** toggle is on, but in `background` mode nothing schedules anything. Celery Beat only exists in the Docker stack, which needs Redis and Postgres, and port 8000 is already taken by another Docker project on this machine (waterhub). There is no Windows-friendly scheduler.

### C. Alerts cannot reach you
6. All three channels are ticked but **no channel has credentials**, so every run records `not_configured` and stays silent. There is no "send test alert" button to show this.
7. Telegram **Interested / Skip** buttons need a public HTTPS webhook. On a laptop they would spin forever.
8. There is **no in-app inbox**: the dashboard never shows which jobs were alerted or which are new since you last looked.

### D. Cost and robustness defects
9. **Saving preferences wipes every AI match**, even when you only tick a notification box. The next run then re-spends up to 50 evaluations. Saving the profile unchanged does the same.
10. A job whose evaluation fails is retried on every run with no counter or backoff.
11. Cross-post dedupe scans every job row in Python per new job (O(n²)); `/api/state` returns every job with its full description every 8 seconds; no pagination or archival. Fine at 20 jobs, painful at 2,000.
12. Preparation **fails outright** if the reviewer flags one unsupported sentence. There is no automatic revision pass, so you retry blind and pay again.

### E. Dashboard gaps
13. `strengths` from the match are never rendered. No posted date, no sort by date, no "new" marker, no pagination, no hide-expired.
14. The compiled `dashboard/` bundle is current, but `pnpm` is not installed, so any UI change needs `corepack` to enable pnpm and a rebuild.

### F. Housekeeping
15. README says Python 3.12; the venv is 3.11 and works. README's Docker quick start conflicts with port 8000 here.
16. `app/api/[...path]/route.ts`, `chatgpt-auth.ts`, drizzle and wrangler files belong to a hosted-dashboard template and are unused locally. Leave them; not harmful.

## 4. Implementation plan

Each phase leaves the app runnable. Phases 1 to 3 deliver the stated goal; 4 to 6 harden and polish.

### Phase 1: Make discovery produce jobs
- **1.1 ReliefWeb.** Migrate to v2 (`appname` from the form, your action). Add an **RSS fallback** now: `reliefweb.int/jobs/rss.xml?search=...` gives title, org, country, closing date and link without registration; the connector fetches each new job page once for the full description, rate-limited and cached by URL.
- **1.2 Generic connectors.** (a) Any RSS/Atom feed URL. (b) A **career-page URL** connector: fetch a public listing page, AI extracts postings (same `JobBatch` pattern the Gmail connector uses), then fetch each posting for full text. This covers employers with custom portals.
- **1.3 More ATS connectors with public JSON APIs**, all probed live and responding: Workable, SmartRecruiters, Ashby, plus Remotive for remote data/ML roles. Keep Greenhouse and Lever.
- **1.4 Gmail helper.** `deployment/gmail_setup.py` runs the installed-app OAuth flow locally (opens browser, catches the redirect on localhost, writes the refresh token to `.env`). You create the OAuth client in Google Cloud once; the script guides that.
- **1.5 Relevance pre-filter.** Stem/token matching (data scien*, climat*, hydrolog*, geospat*/GIS, remote sens*, agricultur*, machine learn*/ML) with title boost. Soft location preference (Ethiopia / Remote / Africa / global) that can be set to strict. AI budget prioritises newest and title-matching jobs.
- **1.6 Suggested sources panel** seeded for your sector, listing only entries that returned 200 during implementation.

### Phase 2: Run continuously on Windows without Docker
- **2.1** In-process scheduler in the FastAPI lifespan: an asyncio task runs a scan every N hours (interval set in Preferences) when the schedule is enabled, with a single-instance lock stored in the DB and automatic repair of stale `running` runs on startup.
- **2.2** `run.ps1` launcher and an optional script that registers the service in Windows Task Scheduler to start at logon.
- **2.3** The Celery/Docker path stays unchanged.

### Phase 3: Alerts that reach you
- **3.1 Telegram without a public URL.** Extend `telegram_setup.py` to discover your chat ID via `getUpdates`. Handle Interested / Skip through a long-polling loop inside the scheduler, so no webhook or HTTPS is needed. Omit the URL button when `PUBLIC_URL` is localhost and put the link in the text.
- **3.2 Test buttons.** `POST /api/notify/test/{channel}` and a button per channel in Preferences.
- **3.3 In-app inbox.** A "New matches" view with unread state; alert records rendered with their delivery status.
- **3.4 Digest mode.** Option to send one message per run listing the top matches instead of one message per job.

### Phase 4: Cost and robustness
- **4.1** Invalidate matches only when the set of verified facts or the keyword list actually changes (hash compare). Threshold and channel changes never invalidate.
- **4.2** Per-job evaluation attempt counter with backoff; skip expired jobs; archive jobs unseen for 45 days and never shortlisted.
- **4.3** Dedupe lookup by a `body:<hash>` record key; list endpoint without descriptions plus a detail endpoint; poll runs only, not the whole state.
- **4.4** One automatic revision pass: reviewer findings are fed back to the writer before an application is marked failed.
- **4.5** Trim oversized descriptions before sending to the model.

### Phase 5: Dashboard
- Install pnpm via corepack, rebuild `dashboard/` as part of the work.
- Opportunities: strengths, posted date, "new" badge, sort by score or date, pagination, hide expired.
- Sources: new source kinds with per-kind help, a "Test source" button that shows how many postings came back, suggested sources.
- Preferences: scan interval, location strictness, digest toggle, test-alert buttons.
- Applications: show reviewer notes; better DOCX layout (headings, bullets, contact block).

### Phase 6: Docs and tests
- README rewritten for the Windows-local flow (venv, launcher, Task Scheduler, Telegram, Gmail).
- Tests for every new connector (mock transport), the scheduler lock, the pre-filter, match invalidation and Telegram polling.

## 5. Actions only you can take
1. Request a ReliefWeb appname: https://apidoc.reliefweb.int/parameters#appname (the RSS fallback works meanwhile).
2. Create a Telegram bot with BotFather and send it one message; the setup script does the rest.
3. If you want email alerts: an SMTP host and an app password.
4. If you want LinkedIn alerts: a Google Cloud project with the Gmail API enabled and an OAuth desktop client; the helper script walks through the rest.

## 6. Decisions to confirm before implementation
1. **Fetching public job pages.** The RSS fallback and career-page connector fetch specific public pages you configure (rate-limited, no login, no LinkedIn). The current docs say "no arbitrary website crawlers". Confirm this targeted fetching is acceptable.
2. **Scheduler inside the API process** (recommended, simplest on Windows) rather than a separate worker.
3. **Channels.** Recommend Telegram plus in-app inbox first; email optional; WhatsApp deferred (Twilio template approval).

## 7. Implementation status (2026-09-20)

All six phases are implemented and the backend suite passes (48 tests, mocked providers, no network).

| Item | Status |
|---|---|
| 1.1 ReliefWeb v2 + RSS fallback | Done. v2 searches title and body with the configured appname; fallback reads the public feed and each new job page. Transient disconnects are retried. |
| 1.2 RSS/Atom and careers-page connectors | Done. Pages are fetched only for configured sources, 60 per run, 1 s apart, known URLs skipped. |
| 1.3 Workable, SmartRecruiters, Ashby, Remotive | Done, with mocked contract tests; Workable (`cgiar`), Ashby and Remotive verified live. |
| 1.4 Gmail OAuth helper | Done (`deployment/gmail_setup.py`, loopback flow). Needs one interactive run by the owner. |
| 1.5 Stem-based screening, priority, location mode | Done. Multi-word keywords must occur as a phrase (window of one extra word, any order). |
| 1.6 Suggested sources | Done; four suggestions added and verified live. |
| 2.1 In-process scheduler + stale repair | Done (`career/scheduler.py`); runs every N hours from Preferences. |
| 2.2 Windows launcher + Task Scheduler | Done (`run.ps1`, `deployment/register_windows_task.ps1`). |
| 3.1 Telegram long polling + in-app linking | Done (`career/telegram.py`); URL button only on HTTPS deployments. |
| 3.2 Test-alert endpoint and buttons | Done. |
| 3.3 In-app inbox | Done: `inapp` alert records, unread badge, "New" filter, mark-read. |
| 3.4 Digest mode | Done. |
| 4.1 Smart invalidation | Done: only verified-evidence or keyword/location/contract changes discard evaluations. |
| 4.2 Backoff and archiving | Done: 3 attempts then 24 h pause; unshortlisted postings unseen for 45 days archived. |
| 4.3 Indexed dedupe, list/detail split | Done: `body:<hash>` index; `/api/state` lists without descriptions; `/api/jobs/{id}` detail. |
| 4.4 Revision pass | Done: reviewer objections trigger one rewrite before failure; notes shown in the dashboard. |
| 4.5 Description trimming | Done (30,000 characters). |
| 5 Dashboard | Done and rebuilt: strengths, posted dates, sort, pagination, hide-closed, inbox, source testing, suggestions, enable/disable sources, test alerts, Telegram linking, interval, location mode, digest, reviewer notes. |
| 6 Docs and tests | Done: README rewritten for the Windows-local flow; ARCHITECTURE updated. |

First live search (2026-09-20): 37 postings from ReliefWeb, Remotive and CGIAR, 35 evaluated in about ten minutes, 3 announced to the inbox (scores 84, 79, 77).

Still needed from the owner: link the Telegram chat from Preferences; run the Gmail helper once to enable email-alert import.


## 8. Multi-user beta (2026-09-20)

Implemented on the same codebase (version 0.3), 58 tests passing:

- Accounts: email + password (scrypt), session cookies, CSRF header, login throttling, invite codes, first account becomes owner and claims pre-account records. SQLite `records` table migrated in place to per-user ownership.
- Bring your own key: per-account OpenAI key verified on entry and stored encrypted (Fernet keyed by `SECRET_KEY`); the owner may use the server key.
- Mailbox source (IMAP with app password) for members' email alerts; Gmail OAuth stays owner-only.
- Per-account Telegram linking on one bot; buttons act only on the pressing user's jobs.
- Scheduler and Celery tasks walk every account's own interval and plan.
- Plans and entitlements (sources, evaluations per search, packages per month, schedule).
- Cohort (admin) tab: totals, per-account activation metrics (verified CV + source; drafted), plan changes, password reset, invitation links.
- Legal pages (`/privacy.html`, `/terms.html`), `render.yaml` Blueprint, deployment guide.

Next: deploy to Render, invite the first 20 to 30 people, watch activation and drafting in the Cohort tab, then add Paddle (Free / Pro) once drafting usage is visible.
