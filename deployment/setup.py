"""Create local secrets once without displaying them. Run from repository root."""

from pathlib import Path
import secrets

destination = Path(".env")
if destination.exists():
    raise SystemExit(".env already exists; preserving your configuration.")
text = Path(".env.example").read_text()
text = text.replace("APP_TOKEN=\n", "APP_TOKEN=" + secrets.token_urlsafe(32) + "\n")
text = text.replace(
    "POSTGRES_PASSWORD=\n", "POSTGRES_PASSWORD=" + secrets.token_hex(24) + "\n"
)
text = text.replace(
    "TELEGRAM_WEBHOOK_SECRET=\n",
    "TELEGRAM_WEBHOOK_SECRET=" + secrets.token_urlsafe(32) + "\n",
)
destination.write_text(text)
destination.chmod(0o600)
print(
    "Created .env. Add your API and messaging credentials, then start Docker Compose."
)
