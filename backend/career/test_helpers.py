"""Small helpers used only by the test suite."""

from .db import Session, User, user_scope, user_snapshot
from .service import evaluation_budget


def evaluation_budget_for(client):
    """The evaluation budget the scoped member would get right now."""
    me = client.get("/api/auth/me").json()
    with Session() as db:
        user = db.get(User, me["id"])
        with user_scope(user_snapshot(user)):
            return evaluation_budget(db)
