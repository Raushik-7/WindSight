"""Engine and session management.

``DATABASE_URL`` selects the backend:

* ``sqlite:////app/data/windsight.db``   (default; file lives on a persistent
  Docker volume so restarts and redeployments keep the imported history)
* ``postgresql+psycopg://user:pass@host:5432/windsight`` (managed PostgreSQL,
  e.g. Supabase or Neon - same schema, same Alembic migrations)

A missing/empty ``DATABASE_URL`` in production must fail loudly rather than
silently falling back to a throwaway local file, so :func:`resolve_database_url`
only applies the SQLite default when ``settings.database_url_is_explicit`` is
false *and* the deployment is not marked production.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger(__name__)

_SQLITE_PREFIXES = ("sqlite",)


def _normalise_scheme(url: str) -> str:
    """Use the installed psycopg 3 driver for provider-style URLs.

    Managed providers hand out ``postgres://`` (Heroku) or ``postgresql://``
    (Render, Supabase, Neon). SQLAlchemy would default to psycopg2, which this
    project does not install, so the driver is pinned explicitly.
    """
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def resolve_database_url(configured: Optional[str], *, allow_sqlite_default: bool = True) -> str:
    """Resolve the database URL, failing safely in production."""
    if configured and configured.strip():
        return _normalise_scheme(configured.strip())
    if not allow_sqlite_default:
        raise RuntimeError(
            "DATABASE_URL is not set. Production deployments must provide a "
            "PostgreSQL connection string; refusing to fall back to a local file."
        )
    return "sqlite:///data/windsight.db"


def build_engine(database_url: str, *, echo: bool = False) -> Engine:
    """Create an engine with sensible settings for SQLite and PostgreSQL."""
    kwargs: dict = {"echo": echo, "future": True, "pool_pre_ping": True}
    if database_url.startswith("sqlite"):
        # SQLite runs on the FastAPI worker threads, so thread ownership checks
        # are disabled and WAL gives us concurrent readers alongside writes.
        directory = Path(database_url.split("///", 1)[-1]).parent
        if str(directory) not in ("", "."):
            directory.mkdir(parents=True, exist_ok=True)
        kwargs["connect_args"] = {"check_same_thread": False}
    engine = create_engine(database_url, **kwargs)

    if database_url.startswith("sqlite"):
        from sqlalchemy import event

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover - driver hook
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()

    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Transactional scope: commits on success, rolls back on any error."""
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def ping(engine: Engine) -> bool:
    """Cheap connectivity probe used by the health endpoint."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # pragma: no cover - exercised in failure tests
        logger.warning("Database ping failed: %s", exc)
        return False


def database_kind(database_url: str) -> str:
    if database_url.startswith(_SQLITE_PREFIXES):
        return "sqlite"
    if database_url.startswith(("postgresql", "postgres")):
        return "postgresql"
    return "other"


def sqlite_path(database_url: str) -> Optional[Path]:
    if not database_url.startswith("sqlite"):
        return None
    return Path(database_url.split("///", 1)[-1])


def sqlite_path_from_env(default: str = "data/windsight.db") -> Path:
    return Path(os.environ.get("DATABASE_URL", default).split("///", 1)[-1])
