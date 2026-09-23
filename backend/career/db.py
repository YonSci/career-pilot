"""Storage.

Every personal record belongs to a user. The current user is carried in a
context variable so service code can keep calling put()/read()/rows() without
threading a user ID through every function; request handlers and background
jobs enter `user_scope()` first. System-wide records (invites, the Telegram
update offset) use the SYSTEM pseudo-user.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import JSON, String, Text, UniqueConstraint, create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.orm.attributes import flag_modified
from .config import settings

SYSTEM = "system"
LEGACY = ""  # records created before accounts existed; claimed by the first admin

_user_id: ContextVar[str] = ContextVar("career_user_id", default=LEGACY)
_user: ContextVar[dict] = ContextVar("career_user", default={})


def now():
    return datetime.now(timezone.utc).isoformat()


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: uuid4().hex)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    password_hash: Mapped[str] = mapped_column(Text, default="")
    role: Mapped[str] = mapped_column(String(16), default="member")  # admin | member
    plan: Mapped[str] = mapped_column(String(16), default="beta")  # free | beta | pro
    created: Mapped[str] = mapped_column(Text, default=now)
    last_active: Mapped[str] = mapped_column(Text, default=now)
    # Encrypted blobs (see auth.seal): openai_key, imap
    secrets: Mapped[dict] = mapped_column(JSON, default=dict)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)

    def public(self):
        return {
            "id": self.id,
            "email": self.email,
            "name": self.name,
            "role": self.role,
            "plan": self.plan,
            "created": self.created,
            "last_active": self.last_active,
            "has_openai_key": bool((self.secrets or {}).get("openai_key")),
            "has_imap": bool((self.secrets or {}).get("imap")),
            "sponsored": bool((self.settings or {}).get("sponsored")),
        }


class Record(Base):
    __tablename__ = "records"
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_records_user_key"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: uuid4().hex)
    user_id: Mapped[str] = mapped_column(String(64), index=True, default=LEGACY)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    key: Mapped[str] = mapped_column(String(256), index=True)
    data: Mapped[dict] = mapped_column(JSON)
    updated: Mapped[str] = mapped_column(Text, default=now)


engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False}
    if settings.database_url.startswith("sqlite")
    else {},
    pool_pre_ping=True,
)
if settings.database_url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def sqlite_pragmas(connection, _):
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=30000")


Session = sessionmaker(engine, expire_on_commit=False)


def migrate_records_table():
    """Add per-user ownership to a records table created before accounts.
    SQLite cannot drop the old unique index on `key`, so the table is rebuilt."""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "records_legacy" in tables:
        # An earlier attempt was interrupted after the rename: the copy and the
        # drop run in one transaction, so the new table (if any) is empty.
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS records"))
    else:
        if "records" not in tables:
            return
        columns = {c["name"] for c in inspector.get_columns("records")}
        if "user_id" in columns:
            return
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE records RENAME TO records_legacy"))
    # Renaming keeps the old indexes, whose names the new table needs.
    with engine.begin() as conn:
        for index in inspect(engine).get_indexes("records_legacy"):
            if index.get("name"):
                conn.execute(text(f'DROP INDEX IF EXISTS "{index["name"]}"'))
    Base.metadata.create_all(engine, tables=[Record.__table__])
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO records (id, user_id, kind, key, data, updated) "
                "SELECT id, '', kind, key, data, updated FROM records_legacy"
            )
        )
        conn.execute(text("DROP TABLE records_legacy"))


def initialize():
    migrate_records_table()
    Base.metadata.create_all(engine)


# --- user scoping ----------------------------------------------------------------


def current_user_id():
    return _user_id.get()


def current_user():
    """Lightweight snapshot of the scoped user: id, email, role, plan, openai_key."""
    return _user.get()


@contextmanager
def user_scope(user):
    """Run a block as `user` (a User row or a snapshot dict)."""
    snapshot = user if isinstance(user, dict) else user_snapshot(user)
    token_id = _user_id.set(snapshot["id"])
    token_user = _user.set(snapshot)
    try:
        yield snapshot
    finally:
        _user_id.reset(token_id)
        _user.reset(token_user)


def user_snapshot(user: User):
    from .auth import unseal  # local import: auth depends on this module

    secrets = user.secrets or {}
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "plan": user.plan,
        "openai_key": unseal(secrets.get("openai_key")) or "",
        "imap": unseal(secrets.get("imap")) or None,
        "sponsored": bool((user.settings or {}).get("sponsored")),
    }


def set_scope(snapshot):
    """Enter a user scope for the current task without a context manager
    (request handlers: the task context ends with the request)."""
    _user_id.set(snapshot["id"])
    _user.set(snapshot)


def find(db, key, user_id=None):
    owner = current_user_id() if user_id is None else user_id
    return db.query(Record).filter_by(user_id=owner, key=key).first()


def put(db, kind, key, data, user_id=None):
    owner = current_user_id() if user_id is None else user_id
    row = db.query(Record).filter_by(user_id=owner, key=key).first()
    # Callers keep updating progress dictionaries after a save. Own a separate
    # snapshot so those edits cannot silently mutate SQLAlchemy's JSON baseline.
    snapshot = deepcopy(data)
    if row:
        row.data, row.updated = snapshot, now()
        flag_modified(row, "data")
    else:
        row = Record(user_id=owner, kind=kind, key=key, data=snapshot)
        db.add(row)
    db.commit()
    return row


def read(db, key, default=None, user_id=None):
    owner = current_user_id() if user_id is None else user_id
    row = db.query(Record).filter_by(user_id=owner, key=key).first()
    return row.data if row else default


def rows(db, kind, user_id=None):
    owner = current_user_id() if user_id is None else user_id
    return db.query(Record).filter_by(user_id=owner, kind=kind).all()


def get_row(db, id, kind=None):
    """A record by ID, only if it belongs to the scoped user."""
    row = db.get(Record, id)
    if not row or row.user_id != current_user_id():
        return None
    if kind and row.kind != kind:
        return None
    return row


def delete_row(db, row):
    db.delete(row)
    db.commit()
