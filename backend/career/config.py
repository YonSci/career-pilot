from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_name: str = "Career Pilot"
    database_url: str = "sqlite:///./data/career.db"
    data_dir: Path = Path("data")
    app_token: str = ""
    # Encrypts stored per-user secrets. Defaults to APP_TOKEN; changing it invalidates stored keys.
    secret_key: str = ""
    # Set to false once the beta is over to allow open sign-up.
    invite_only: bool = True
    # Optional: only this address may create the first (owner) account. Otherwise
    # the first sign-up must present APP_TOKEN as the setup code.
    owner_email: str = ""
    cors_origins: str = "http://localhost:8000,http://localhost:3000"
    public_url: str = "http://localhost:8000"
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
    # Politeness limits for connectors that read individual public posting pages.
    max_page_fetches_per_run: int = 60
    fetch_delay_seconds: float = 1.0
    # Description text sent to the matching model is trimmed to this length.
    match_description_chars: int = 30000
    # Evaluations that keep failing are paused for this many hours after 3 attempts.
    match_retry_hours: int = 24
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
    gmail_query: str = "label:CareerPilot newer_than:7d"
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    whatsapp_from: str = ""
    whatsapp_to: str = ""
    whatsapp_content_sid: str = ""
    reliefweb_appname: str = ""

    @property
    def public_https(self) -> bool:
        return self.public_url.lower().startswith("https://")


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
