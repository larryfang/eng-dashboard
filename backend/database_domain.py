"""
Domain-scoped database for dashboard data.

Each domain (director's org) gets its own SQLite file:
  data/domains/ecosystem.db
  data/domains/platform.db   (future)

This is completely separate from eng_dashboard.db (legacy data).
"""
import logging
import re
from pathlib import Path
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import declarative_base, sessionmaker, Session

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOMAINS_DIR = PROJECT_ROOT / "data" / "domains"

DomainBase = declarative_base()


_SLUG_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def get_domain_db_path(domain_slug: str) -> Path:
    if not _SLUG_RE.match(domain_slug):
        raise ValueError(f"Invalid domain slug: {domain_slug!r}")
    DOMAINS_DIR.mkdir(parents=True, exist_ok=True)
    return DOMAINS_DIR / f"{domain_slug}.db"


def create_domain_engine(domain_slug: str):
    db_path = get_domain_db_path(domain_slug)
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(conn, _):
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


# --- Multi-domain engine pool ---
_engines: dict = {}   # slug → Engine
_sessions: dict = {}  # slug → sessionmaker


def get_domain_engine(domain_slug: str):
    """Get (or create) the SQLAlchemy engine for a domain slug."""
    if domain_slug not in _engines:
        _engines[domain_slug] = create_domain_engine(domain_slug)
    return _engines[domain_slug]


def get_domain_session(domain_slug: str):
    """FastAPI dependency: yields a session for the given domain slug."""
    if domain_slug not in _sessions:
        _sessions[domain_slug] = sessionmaker(
            autocommit=False, autoflush=False, bind=get_domain_engine(domain_slug)
        )
    db = _sessions[domain_slug]()
    try:
        yield db
    finally:
        db.close()


# --- Backward-compat: active domain shims (used by all existing routers) ---

def get_ecosystem_engine():
    """Get engine for the currently active domain (backward compat)."""
    from backend.services.domain_registry import get_active_slug
    return get_domain_engine(get_active_slug())


def get_ecosystem_session():
    """FastAPI dependency: yields a session for the currently active domain."""
    from backend.services.domain_registry import get_active_slug
    yield from get_domain_session(get_active_slug())


def create_ecosystem_session() -> Session:
    """Create a standalone session for the active domain (caller must close).

    Use this instead of next(get_ecosystem_session()) for background tasks and
    helper functions that are not FastAPI dependency-injected.  The caller is
    responsible for calling session.close() in a try/finally block.
    """
    from backend.services.domain_registry import get_active_slug
    slug = get_active_slug()
    if slug not in _sessions:
        _sessions[slug] = sessionmaker(
            autocommit=False, autoflush=False, bind=get_domain_engine(slug)
        )
    return _sessions[slug]()


def init_domain_db(domain_slug: str | None = None):
    """Create all domain tables for a slug (or active domain if None)."""
    from backend.models_domain import DomainBase as ModelBase
    if domain_slug is None:
        from backend.services.domain_registry import get_active_slug
        domain_slug = get_active_slug()
    ModelBase.metadata.create_all(bind=get_domain_engine(domain_slug))


def init_all_domain_dbs():
    """Initialise DB tables for every configured domain."""
    from backend.core.config_loader import list_domain_slugs
    for slug in list_domain_slugs():
        init_domain_db(slug)


# ---------------------------------------------------------------------------
# Schema migrations (additive only — SQLite ALTER TABLE ADD COLUMN)
# ---------------------------------------------------------------------------

_MIGRATIONS = [
    # (table, column, type)  — only additive operations
    ("port_services", "team", "TEXT"),
    ("port_services", "language_version", "TEXT"),
]

_INDEX_MIGRATIONS = [
    "CREATE INDEX IF NOT EXISTS ix_mr_author_created ON mr_activity (author_username, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_port_services_team ON port_services (team)",
]


def migrate_domain_db(domain_slug: str) -> None:
    """Run pending additive schema migrations for a domain DB.

    SQLite supports ALTER TABLE ADD COLUMN but not IF NOT EXISTS, so we attempt
    each addition and silently ignore errors when the column already exists.
    """
    engine = get_domain_engine(domain_slug)
    with engine.connect() as conn:
        for table, column, col_type in _MIGRATIONS:
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
                conn.commit()
                logger.info("Migration: added %s.%s (%s)", table, column, domain_slug)
            except Exception:
                pass  # column already exists — safe to ignore

        for idx_sql in _INDEX_MIGRATIONS:
            try:
                conn.execute(text(idx_sql))
                conn.commit()
            except Exception:
                pass  # index already exists or table doesn't exist yet


def migrate_all_domain_dbs() -> None:
    """Run migrations for every configured domain."""
    from backend.core.config_loader import list_domain_slugs
    for slug in list_domain_slugs():
        migrate_domain_db(slug)
