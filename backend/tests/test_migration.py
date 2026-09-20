"""The pre-account records table (unique key, kind index) must migrate in place,
including when a previous attempt was interrupted after the rename."""

import json
from sqlalchemy import text, inspect
from career.db import engine, initialize, Session, Record, User, Base

OLD_SCHEMA = """
CREATE TABLE records (
    id VARCHAR(64) NOT NULL PRIMARY KEY,
    kind VARCHAR(32) NOT NULL,
    "key" VARCHAR(256) NOT NULL UNIQUE,
    data JSON NOT NULL,
    updated TEXT NOT NULL
);
CREATE INDEX ix_records_kind ON records (kind);
"""


def make_old_database():
    Base.metadata.drop_all(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS records_legacy"))
        for statement in OLD_SCHEMA.strip().split(";"):
            if statement.strip():
                conn.execute(text(statement))
        conn.execute(
            text("INSERT INTO records (id, kind, key, data, updated) VALUES (:i, :k, :y, :d, :u)"),
            [
                {"i": "a1", "k": "profile", "y": "profile", "d": json.dumps({"name": "Legacy"}), "u": "2026-01-01"},
                {"i": "b2", "k": "job", "y": "job:x", "d": json.dumps({"title": "Old job"}), "u": "2026-01-02"},
            ],
        )


def test_records_table_migrates_and_keeps_rows():
    make_old_database()
    initialize()
    names = set(inspect(engine).get_table_names())
    assert "records_legacy" not in names and "users" in names
    with Session() as db:
        rows = db.query(Record).order_by(Record.id).all()
        assert [(r.id, r.user_id, r.kind) for r in rows] == [("a1", "", "profile"), ("b2", "", "job")]
        assert rows[0].data == {"name": "Legacy"}
    initialize()  # idempotent


def test_interrupted_migration_resumes():
    make_old_database()
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE records RENAME TO records_legacy"))
    initialize()
    with Session() as db:
        assert db.query(Record).count() == 2
        assert db.query(User).count() == 0


def test_backup_and_restore_round_trip(client, monkeypatch):
    """Owner downloads a backup; an empty instance restores it with the setup code."""
    from io import BytesIO
    from tests.test_workflow import JOB, verified_profile
    from tests.conftest import reset_database
    from fastapi.testclient import TestClient
    from career.main import app

    verified_profile(client)
    client.post("/api/jobs", json=JOB)
    r = client.get("/api/admin/backup")
    assert r.status_code == 200 and r.content.startswith(b"SQLite format 3")
    backup = r.content
    reset_database()
    with TestClient(app) as anon:
        assert anon.get("/api/setup").json()["needs_first_account"] is True
        # Wrong code, garbage file, then a real restore.
        assert anon.post("/api/admin/restore", files={"file": ("b.db", backup)}, headers={"Authorization": "Bearer nope"}).status_code == 401
        assert anon.post("/api/admin/restore", files={"file": ("b.db", b"junk")}, headers={"Authorization": "Bearer test-token-only-0123456789abcdef"}).status_code == 422
        r = anon.post("/api/admin/restore", files={"file": ("b.db", backup)}, headers={"Authorization": "Bearer test-token-only-0123456789abcdef"})
        assert r.status_code == 200 and r.json()["accounts"] == 1 and r.json()["records"] >= 3
        assert anon.get("/api/setup").json()["needs_first_account"] is False
        # The restored owner can sign in and sees their data.
        assert anon.post("/api/auth/login", json={"email": "owner@example.org", "password": "owner-password-123"}, headers={"X-Requested-With": "CareerPilot"}).status_code == 200
        state = anon.get("/api/state").json()
        assert state["profile"]["name"] == "Example Applicant" and len(state["jobs"]) == 1
        # A second restore is refused now that accounts exist.
        assert anon.post("/api/admin/restore", files={"file": ("b.db", backup)}, headers={"Authorization": "Bearer test-token-only-0123456789abcdef"}).status_code == 409
