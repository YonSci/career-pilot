from pathlib import Path
from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_name: str = "Jobs Find AI"
    database_url: str = "sqlite:///./data/career.db"
    data_dir: Path = Path("data")
    app_token: str = ""
    # Encrypts stored per-user secrets. Defaults to APP_TOKEN; changing it invalidates stored keys.
    secret_key: str = ""
    # Set to false once the beta is over to allow open sign-up.
    invite_only: bool = True
    # While invite-only, this many people a day (rolling 24 hours) may join
    # without a code: the sign-up form and "Request an invite" let them in
    # straight away. Beyond that they need a code. 0 = codes only.
    open_seats_per_day: int = 25
    # Optional: only this address may create the first (owner) account. Otherwise
    # the first sign-up must present APP_TOKEN as the setup code.
    owner_email: str = ""
    # The first N members to register use the server's OpenAI key (sponsored
    # seats) with the "sponsored" plan's monthly caps. 0 disables sponsoring.
    sponsored_seats: int = 20
    cors_origins: str = "http://localhost:8000,http://localhost:3000"
    public_url: str = "http://localhost:8000"
    # Set by Render on every deploy; /health reports it so a deploy can be matched to a commit.
    render_git_commit: str = ""
    openai_api_key: str = ""
    extract_model: str = "gpt-5.6-luna"
    match_model: str = "gpt-5.6-terra"
    write_model: str = "gpt-5.6-sol"
    redis_url: str = "redis://redis:6379/0"
    task_queue: str = "background"
    # In-process scheduler (background mode only). Celery Beat owns scheduling in Docker.
    scheduler_enabled: bool = True
    max_matches_per_run: int = 50
    # Concurrent model calls during a search (evaluations and email extraction).
    evaluation_workers: int = 4
    # Accounts whose scheduled searches may run at the same time.
    scan_workers: int = 2
    # Sources still unread after this many minutes are deferred to the next search.
    scan_time_budget_minutes: int = 20
    # A channel enabled later still receives matches evaluated within this many days.
    alert_catchup_days: int = 7
    # Politeness limits for connectors that read individual public posting pages.
    max_page_fetches_per_run: int = 60
    fetch_delay_seconds: float = 1.0
    # Description text sent to the matching model is trimmed to this length.
    match_description_chars: int = 30000
    # Evaluations that keep failing are paused for this many hours after 3 attempts.
    match_retry_hours: int = 24
    # JEV (TypeSafe AI) ranks postings cheaply before the LLM evaluates them.
    # "off": unused. "shadow": scored and stored for comparison, LLM order unchanged.
    # "rank": the LLM evaluates postings in JEV order and skips confident low scores.
    jev_mode: Literal["off", "shadow", "rank"] = "off"
    typesafe_api_key: str = ""
    # Pin a dated model (list them with `python -m career.jev_report --models`) so a provider
    # update cannot mix old and new scores; changing it rescores postings as they are next ranked.
    jev_model: str = "jev-latest"
    # Postings JEV scores per search; scores are cached per posting, evidence and preferences.
    jev_max_per_run: int = 300
    jev_workers: int = 8
    # Rank mode: a posting scoring below jev_min_score with at least jev_confident
    # confidence is not sent to the LLM. Uncertain low scores still are.
    jev_min_score: int = 40
    jev_confident: float = 0.6
    # Share of each search's LLM evaluations (rounded down) spent on a random sample
    # of postings rank mode would hold, so the report can measure what JEV would miss.
    jev_sample_share: float = 0.1
    # Hard monthly cap on JEV input tokens, all accounts together; 0 = no cap. Once
    # reached, postings keep keyword order until next month. Set a matching limit with TypeSafe.
    jev_monthly_tokens: int = 20_000_000
    # Who sees JEV scores in the dashboard: "owner" (admin only), "all" members, or "off".
    jev_show: Literal["owner", "all", "off"] = "owner"
    # Comma-separated account emails that use JEV; empty means every account.
    jev_accounts: str = ""
    # Shared catalog: postings from approved public sources are also stored once
    # under SYSTEM; false stops writing and reading it.
    catalog_enabled: bool = True
    # Phase 2: members without an enabled source of their own search the catalog's
    # recent postings instead (starter results). Members with sources are unchanged.
    catalog_starter: bool = True
    # Phase 3: ReliefWeb searches and employer boards are read once for everyone by
    # the shared collector; members' searches skip a source read in the last
    # SHARED_FETCH_HOURS and draw on the whole catalog. Off: members fetch their
    # own sources as before (the owner's curated shared sources are read either way).
    catalog_shared: bool = False
    shared_fetch_hours: float = 3
    # Phase 4: per member and month, this many postings their keywords rejected
    # (at most one per search) are stored and evaluated anyway, so jev_report can
    # show whether keywords miss good jobs. Taken from the search's evaluation
    # budget; never alerted. 0 turns it off.
    keyword_sample_per_month: int = 10
    # Unshortlisted jobs unseen in any feed for this long are archived.
    archive_after_days: int = 45
    dashboard_dir: Path = Path("dashboard")
    # Public marketing page served at /; the app lives under /app.
    landing_dir: Path = Path("landing")
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_webhook_secret: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    email_from: str = ""
    email_to: str = ""
    gmail_client_id: str = ""
    gmail_client_secret: str = ""
    gmail_refresh_token: str = ""
    gmail_query: str = "{label:JobsFindAI label:JobsFindAI} newer_than:7d"
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    whatsapp_from: str = ""
    whatsapp_to: str = ""
    whatsapp_content_sid: str = ""
    reliefweb_appname: str = ""
    # Product analytics, session replay and error tracking (PostHog). Empty = off.
    posthog_key: str = ""
    posthog_host: str = "https://eu.i.posthog.com"
    posthog_replay: bool = True
    # Server-side health events (searches, drafts, failures) to PostHog.
    posthog_server_events: bool = True
    # Hard monthly cap on model calls made with the server's key (owner + sponsored
    # members together). 0 = no cap. Set a matching limit on the OpenAI account too.
    server_key_monthly_calls: int = 4000
    # Per-account limits on manual AI actions per hour (evaluate, extract, test page sources, prepare).
    ai_actions_per_hour: int = 40
    # --- Billing. Prices in whole units; ETB for Ethiopia, USD for cards worldwide.
    price_pro_etb: int = 350
    price_pro_plus_etb: int = 800
    price_package_etb: int = 100
    price_pro_usd: int = 9
    price_pro_plus_usd: int = 19
    price_package_usd: int = 2
    featured_listing_etb: int = 2500
    featured_listing_usd: int = 25
    institution_seat_etb: int = 200
    institution_seat_usd: int = 3
    # Chapa (Ethiopia): secret key from the dashboard; webhook secret hash set in Chapa's webhook settings.
    chapa_secret_key: str = ""
    chapa_webhook_secret: str = ""
    # Lemon Squeezy (cards worldwide): hosted checkout links per product and the webhook signing secret.
    lemon_checkout_pro: str = ""
    lemon_checkout_pro_plus: str = ""
    lemon_checkout_package: str = ""
    # Lemon Squeezy checkout link for a featured employer listing (USD).
    lemon_checkout_featured: str = ""
    lemon_webhook_secret: str = ""
    # Shown to members paying by hand when no gateway is configured (Telebirr number, bank details).
    billing_contact: str = ""
    # --- Growth. Public Telegram channel the bot posts to (@name or numeric id; bot must be admin).
    telegram_channel_id: str = ""
    telegram_channel_daily_hour: int = 7
    # Personal invitation links each member can share.
    referral_invites: int = 3
    # Google Search Console: the content value of the google-site-verification meta tag.
    google_site_verification: str = ""
    # Web push (installable app): VAPID key pair and contact. Generate with deployment/vapid_keys.py.
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = ""

    @property
    def public_https(self) -> bool:
        return self.public_url.lower().startswith("https://")


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
