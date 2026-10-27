"""Programmatic Alembic helpers.

Migrations are the single source of schema truth: the API startup, the Docker
entrypoint and the import CLI all apply pending revisions through this module
instead of calling ``create_all`` (which would drift from Alembic's version
table).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _config(database_url: str):
    from alembic.config import Config

    ini_path = BACKEND_ROOT / "alembic.ini"
    config = Config(str(ini_path))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def upgrade_head(database_url: str) -> str:
    """Apply every pending revision. Returns the resulting revision id."""
    from alembic import command

    command.upgrade(_config(database_url), "head")
    return current_revision(database_url) or "head"


def current_revision(database_url: str) -> Optional[str]:
    from alembic.command import current as alembic_current
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy import create_engine

    engine = create_engine(database_url, future=True)
    try:
        with engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()


def schema_exists(database_url: str) -> bool:
    """True when the initial revision has already been applied."""
    return current_revision(database_url) is not None
