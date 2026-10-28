"""One-off reminder to members who have job sources but scheduled searches off.
Lists who would be reminded, and through which channel, unless --send is given.
Each member is reminded once; a second run skips them.

    python -m career.schedule_reminder           (dry run: lists recipients and the message)
    python -m career.schedule_reminder --send
"""

import sys
from .auth import plan_limits
from .config import settings
from .db import Session, User, now, put, read, rows, user_scope, user_snapshot
from .notifications import email_send, telegram_send

SUBJECT = "Your job search can run on its own"


def message(name):
    url = settings.public_url.rstrip("/") + "/app/"
    return (
        f"Hello{' ' + name if name else ''},\n\n"
        f"You have job sources set up in {settings.app_name}, but scheduled searches are off. "
        "New postings are only checked when you click Run search, so jobs that close quickly can be missed.\n\n"
        f"To have them checked every few hours, even when you are offline, open {url}, go to Preferences, "
        "and switch on \"Search automatically\" under Scheduled searches. "
        "Strong matches then reach you through the alert channels you have chosen.\n\n"
        "If you prefer to search by hand, you don't need to do anything.\n\n"
        f"{settings.app_name}"
    )


def recipients(db):
    """(user, channels) for members to remind: schedule allowed but off, an enabled source, not reminded yet."""
    found = []
    for user in db.query(User).filter(User.role != "admin").all():
        if not plan_limits(user.plan)["schedule"]:
            continue
        with user_scope(user_snapshot(user)):
            if (read(db, "schedule", {}) or {}).get("enabled") or read(db, "schedule-reminder"):
                continue
            if not any(s.data.get("enabled") for s in rows(db, "source")):
                continue
            channels = []
            if settings.smtp_host and settings.email_from:
                channels.append("email")
            if settings.telegram_bot_token and (read(db, "telegram", {}) or {}).get("chat_id"):
                channels.append("telegram")
        found.append((user, channels))
    return found


def main(argv=None):
    send = "--send" in (sys.argv[1:] if argv is None else argv)
    with Session() as db:
        found = recipients(db)
        if not found:
            print("No members to remind.")
            return
        for user, channels in found:
            print(f"{user.email}: {', '.join(channels) or 'no channel configured (skipped)'}")
        if not send:
            print("\nDry run. Message:\n\n" + SUBJECT + "\n\n" + message("<name>") + "\n\nRun again with --send to send it.")
            return
        sent = 0
        for user, channels in found:
            delivered = []
            text = message(user.name)
            with user_scope(user_snapshot(user)):
                for channel in channels:
                    try:
                        if channel == "email":
                            email_send(SUBJECT, text, to=user.email)
                        else:
                            telegram_send(read(db, "telegram")["chat_id"], text)
                        delivered.append(channel)
                    except Exception as e:
                        print(f"{user.email}: {channel} failed ({type(e).__name__})")
                if delivered:
                    put(db, "schedule-reminder", "schedule-reminder", {"sent": now(), "channels": delivered})
                    sent += 1
        print(f"Reminded {sent} of {len(found)} members.")


if __name__ == "__main__":
    main()
