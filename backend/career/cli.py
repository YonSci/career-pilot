"""Manual collection for cron / Windows Task Scheduler without a running server.
Runs a search for every account whose schedule is enabled and due."""

from .db import initialize
from .scheduler import due_users, scheduled_scan

if __name__ == "__main__":
    initialize()
    users = due_users()
    for user in users:
        scheduled_scan(user)
    print(f"Searched {len(users)} account(s). Open the dashboard for results.")
