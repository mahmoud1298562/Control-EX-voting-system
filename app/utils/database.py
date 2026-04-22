import os
import logging
from sqlalchemy import create_engine, event as sa_event, text
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager
from app.models import Base

log = logging.getLogger(__name__)

_RAW_URL = os.getenv("DATABASE_URL")
if not _RAW_URL:
    raise RuntimeError(
        "DATABASE_URL environment variable is not set. "
        "Set it in .env, e.g.: DATABASE_URL=sqlite:////data/event_system.db"
    )

DATABASE_URL = _RAW_URL
_IS_SQLITE = "sqlite" in DATABASE_URL

# ── Engine ────────────────────────────────────────────────────────────────────
_connect_args: dict = {}
if _IS_SQLITE:
    _connect_args = {
        "check_same_thread": False,
        "timeout": 30,           # seconds to wait for a lock before raising
    }

engine = create_engine(
    DATABASE_URL,
    connect_args=_connect_args,
    pool_pre_ping=True,          # detect stale connections
    pool_recycle=1800,           # recycle connections every 30 min
)

# ── SQLite hardening: WAL mode + pragmas (applied once per connection) ────────
if _IS_SQLITE:
    @sa_event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_conn, _connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")       # concurrent reads + writes
        cursor.execute("PRAGMA synchronous=NORMAL")     # safe + faster than FULL
        cursor.execute("PRAGMA busy_timeout=5000")      # 5 s wait on locked DB
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA temp_store=MEMORY")      # temp tables in RAM
        cursor.execute("PRAGMA mmap_size=268435456")    # 256 MB memory-mapped I/O
        cursor.close()

# ── Session factory ───────────────────────────────────────────────────────────
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """FastAPI dependency — yields a DB session, always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_ctx():
    """Context-manager version for use outside FastAPI dependency injection."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables and verify WAL is active."""
    Base.metadata.create_all(bind=engine)
    if _IS_SQLITE:
        with engine.connect() as conn:
            mode = conn.execute(text("PRAGMA journal_mode")).scalar()
            log.info("SQLite journal_mode = %s", mode)


# ── Atomic scan check-in  ─────────────────────────────────────────────────────
def atomic_checkin(db: Session, user_id: str) -> dict:
    """
    Atomically mark a user as attended.

    Uses a raw UPDATE with WHERE clause to prevent TOCTOU race conditions —
    the DB row is only modified if attended=0, and we read the result back.
    Returns dict with keys: status ('success'|'already_scanned'|'not_found'),
    name, attended_at.
    """
    from datetime import datetime, timezone
    from app.models import User

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # Single atomic UPDATE: only fires if attended is currently False
    result = db.execute(
        text(
            "UPDATE users SET attended=1, attended_at=:ts "
            "WHERE id=:uid AND attended=0"
        ),
        {"ts": now, "uid": user_id},
    )
    db.commit()

    if result.rowcount == 1:
        # We just checked them in — fetch name for the response
        user = db.get(User, user_id)
        return {
            "status": "success",
            "name": user.name if user else "Attendee",
            "attended_at": now,
        }

    # rowcount == 0: either already attended or user doesn't exist
    user = db.get(User, user_id)
    if user is None:
        return {"status": "not_found", "name": "", "attended_at": None}

    return {
        "status": "already_scanned",
        "name": user.name,
        "attended_at": user.attended_at,
    }


# ── Atomic vote cast ──────────────────────────────────────────────────────────
def atomic_vote(db: Session, user_id: str, project_name: str) -> dict:
    """
    Atomically cast a vote.

    Uses UPDATE WHERE voted=0 to guarantee exactly-once voting even under
    concurrent requests. Returns dict with keys: status, message.
    """
    import uuid as _uuid
    from app.models import User, Vote

    # Only mark voted if currently False
    result = db.execute(
        text("UPDATE users SET voted=1 WHERE id=:uid AND voted=0 AND attended=1"),
        {"uid": user_id},
    )
    if result.rowcount == 0:
        # Check why it failed
        user = db.get(User, user_id)
        if user is None:
            db.rollback()
            return {"status": "error", "message": "User not found."}
        if not user.attended:
            db.rollback()
            return {"status": "error", "message": "You must be checked in to vote."}
        db.rollback()
        return {"status": "error", "message": "You have already voted."}

    # Insert vote record
    vote = Vote(id=str(_uuid.uuid4()), user_id=user_id, project_name=project_name)
    db.add(vote)
    db.commit()
    return {"status": "success", "message": f"Vote for '{project_name}' recorded!"}
