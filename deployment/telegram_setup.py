"""Telegram helper. Never prints tokens.

Default local installs need nothing here: link your chat from the dashboard
(Preferences -> Link Telegram) and the server long-polls for button presses.

Usage:
    python deployment/telegram_setup.py check     # confirm the bot token and show link status
    python deployment/telegram_setup.py webhook   # HTTPS deployments only: register the webhook
    python deployment/telegram_setup.py polling   # remove a webhook so long polling works again
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import httpx
from career.config import settings


def call(method, **payload):
    r = httpx.post(f"https://api.telegram.org/bot{settings.telegram_bot_token}/{method}", json=payload, timeout=30)
    data = r.json()
    if not data.get("ok"):
        raise SystemExit(f"Telegram rejected {method}: {data.get('description', r.status_code)}")
    return data["result"]


def main():
    if not settings.telegram_bot_token:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN in .env first (from BotFather).")
    command = sys.argv[1] if len(sys.argv) > 1 else "check"
    me = call("getMe")
    print(f"Bot @{me.get('username')} is reachable.")
    info = call("getWebhookInfo")
    if command == "check":
        print("Webhook:", info.get("url") or "none (long polling mode)")
        print("Chat ID from .env:", "set" if settings.telegram_chat_id else "not set (link from the dashboard instead)")
        print("Next: open the dashboard -> Preferences -> Link Telegram, then send the code to @" + me.get("username", ""))
    elif command == "webhook":
        if not settings.public_url.startswith("https://"):
            raise SystemExit("Set PUBLIC_URL to the HTTPS address of the Python service first.")
        if not settings.telegram_webhook_secret:
            raise SystemExit("Set TELEGRAM_WEBHOOK_SECRET in .env.")
        call(
            "setWebhook",
            url=settings.public_url.rstrip("/") + "/api/telegram/webhook",
            secret_token=settings.telegram_webhook_secret,
            allowed_updates=["message", "callback_query"],
        )
        print("Webhook registered. The server will no longer long-poll.")
    elif command == "polling":
        call("deleteWebhook")
        print("Webhook removed. Restart the server to resume long polling.")
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
