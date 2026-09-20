import os
import tempfile
from pathlib import Path

temp = Path(tempfile.mkdtemp(prefix="career-test-"))
os.environ.update(
    DATABASE_URL="sqlite:///" + str(temp / "test.db"),
    DATA_DIR=str(temp),
    APP_TOKEN="test-token-only-0123456789abcdef",
    OPENAI_API_KEY="",
    TASK_QUEUE="background",
    SCHEDULER_ENABLED="false",
    FETCH_DELAY_SECONDS="0",
)
import pytest
from fastapi.testclient import TestClient
from career.main import app
from career.db import Session, Record, User, user_scope, user_snapshot

OWNER = {"email": "owner@example.org", "password": "owner-password-123", "name": "Owner"}
CSRF = {"X-Requested-With": "CareerPilot"}


def reset_database():
    from career import auth as accounts

    accounts._attempts.clear()
    with Session() as db:
        db.query(Record).delete()
        db.query(User).delete()
        db.commit()


@pytest.fixture
def client():
    """Signed in as the owner through the APP_TOKEN bearer, like scripts do.
    The owner account is created through the public signup (first account)."""
    with TestClient(app) as client:
        reset_database()
        assert client.post("/api/auth/signup", json=OWNER, headers=CSRF).status_code == 200
        client.cookies.clear()
        client.headers["Authorization"] = "Bearer test-token-only-0123456789abcdef"
        yield client


@pytest.fixture
def owner_scope(client):
    """Enter the owner's scope for direct database work inside a test."""
    with Session() as db:
        user = db.query(User).filter_by(email=OWNER["email"]).one()
        snapshot = user_snapshot(user)
    with user_scope(snapshot):
        yield snapshot


def signup_member(client, email="member@example.org", password="member-password-123", invite=None):
    """A second, cookie-authenticated client for isolation tests."""
    if invite is None:
        invite = client.post("/api/admin/invites", json={"count": 1}).json()["codes"][0]
    member = TestClient(app)
    r = member.post("/api/auth/signup", json={"email": email, "password": password, "invite": invite}, headers=CSRF)
    assert r.status_code == 200, r.text
    member.headers.update(CSRF)
    return member
