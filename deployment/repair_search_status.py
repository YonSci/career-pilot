"""Run once with the local Python server stopped; backs up SQLite before repairs."""

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from career.config import settings
from career.db import Session, Record, engine, now, put


def main():
    if engine.dialect.name != "sqlite":
        raise SystemExit("This repair is for the local SQLite setup only.")
    database = engine.url.database
    if not database or database == ":memory:" or not Path(database).is_file():
        raise SystemExit("No existing SQLite database found. Run from your Career Pilot project folder.")

    with Session() as db:
        runs = [r for r in db.query(Record).filter_by(kind="run").all()
                if r.data.get("status") in ("queued", "running")]
        if not runs:
            print("No unfinished search entries to repair.")
            return

        backup_dir = settings.data_dir / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = backup_dir / ("before-search-repair-" + stamp + ".sqlite3")
        raw = engine.raw_connection()
        destination = sqlite3.connect(str(backup))
        try:
            raw.driver_connection.backup(destination)
        finally:
            destination.close()
            raw.close()

        for run in runs:
            put(db, "run", run.key, {
                **run.data,
                "status": "interrupted",
                "completed": now(),
                "error": "This earlier search did not record a final status. Start a new search after checking your sources.",
            })
        print(f"Repaired {len(runs)} unfinished search entries. Existing CV, jobs and applications were preserved.")
        print(f"Database backup: {backup.resolve()}")


if __name__ == "__main__":
    main()
