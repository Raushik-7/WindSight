"""Durable store used by the analytics service.

The API reads observations from the database - never from a fresh upstream
call.  An in-process memo makes repeated requests cheap, and every write path
(e.g. an operator refresh) invalidates it explicitly.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import Settings
from .db import repository
from .db.session import (
    build_engine,
    create_session_factory,
    database_kind,
    ping,
    resolve_database_url,
    session_scope,
)
from .models import SourceData
from .source import DataUnavailableError

logger = logging.getLogger(__name__)

UTC = timezone.utc


class DatabaseStore:
    """Read-through accessor for the durable observation tables."""

    def __init__(
        self,
        settings: Settings,
        *,
        engine: Optional[Engine] = None,
        session_factory: Optional[sessionmaker[Session]] = None,
    ) -> None:
        self.settings = settings
        self.database_url = resolve_database_url(
            settings.database_url,
            allow_sqlite_default=settings.deployment_env != "production",
        )
        self.engine = engine or build_engine(self.database_url)
        self.session_factory = session_factory or create_session_factory(self.engine)
        self._lock = threading.Lock()
        self._cached: Optional[SourceData] = None

    # ------------------------------------------------------------------ #
    def load(self, force_refresh: bool = False) -> SourceData:
        with self._lock:
            if self._cached is not None and not force_refresh:
                return self._cached

            if not ping(self.engine):
                raise DataUnavailableError(
                    "Database is unreachable. Check DATABASE_URL and that the "
                    "database service is running."
                )

            with session_scope(self.session_factory) as session:
                actual_count = repository.count_actuals(session)
                forecast_count = repository.count_forecasts(session)
                if actual_count == 0 or forecast_count == 0:
                    raise DataUnavailableError(
                        "No imported history is available yet. Run "
                        "`python -m app.scripts.import_historical_data` (see README)."
                    )
                actuals = repository.load_actuals(session)
                forecasts = repository.load_forecasts(session)
                runs = repository.latest_imports(session, limit=5)
                publication_low, publication_high = repository.forecast_publication_range(session)

            successful = [run for run in runs if run.status == "completed"]
            retrieved_at = (
                successful[0].finished_at if successful else (runs[0].finished_at if runs else None)
            )
            retrieved_at = _as_utc(retrieved_at) or datetime.now(UTC)

            latest_summary = (
                f"last import #{runs[0].id} {runs[0].status} ({runs[0].source})"
                if runs
                else "no import runs recorded"
            )
            source = SourceData(
                actuals=actuals,
                forecasts=forecasts,
                retrieved_at=retrieved_at,
                origin="database",
                origin_detail=(
                    f"database ({database_kind(self.database_url)}): "
                    f"{actual_count} actual / {forecast_count} forecast records; {latest_summary}"
                ),
                exclusions=[],
                fetch_errors=[],
                upstream_requests=0,
            )
            source.extra = {
                "actual_count": actual_count,
                "forecast_count": forecast_count,
                "publication_low": publication_low,
                "publication_high": publication_high,
                "runs": runs,
                "last_import_run": _run_to_dict(runs[0]) if runs else None,
                "database_kind": database_kind(self.database_url),
                "database_url": _redact(self.database_url),
            }
            self._cached = source
            return source

    def invalidate(self) -> None:
        with self._lock:
            self._cached = None

    # ------------------------------------------------------------------ #
    def health(self) -> dict[str, Any]:
        """Used by /api/health; never raises."""
        payload: dict[str, Any] = {
            "database_url": _redact(self.database_url),
            "database_kind": database_kind(self.database_url),
            "reachable": False,
        }
        try:
            payload["reachable"] = ping(self.engine)
        except Exception as exc:  # pragma: no cover - defensive
            payload["error"] = str(exc)
            return payload

        if not payload["reachable"]:
            return payload

        try:
            with session_scope(self.session_factory) as session:
                payload["actual_records"] = repository.count_actuals(session)
                payload["forecast_records"] = repository.count_forecasts(session)
                runs = repository.latest_imports(session, limit=3)
                payload["last_import"] = _run_to_dict(runs[0]) if runs else None
        except Exception as exc:  # pragma: no cover - defensive
            payload["error"] = str(exc)
        return payload

    def import_runs(self, limit: int = 10) -> list[dict[str, Any]]:
        with session_scope(self.session_factory) as session:
            return [_run_to_dict(run) for run in repository.latest_imports(session, limit=limit)]

    def run_import(self, *, source: str = "elexon_live") -> list[dict[str, Any]]:
        """Controlled refresh used by the protected admin endpoint."""
        from .importer import refresh, result_to_dict

        with session_scope(self.session_factory) as session:
            results = refresh(session, self.settings, source=source)
        self.invalidate()
        return [result_to_dict(result) for result in results]


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _redact(url: str) -> str:
    """Hide credentials before a connection string reaches a response body."""
    if "@" in url and "://" in url:
        scheme, rest = url.split("://", 1)
        credentials, host = rest.rsplit("@", 1)
        user = credentials.split(":", 1)[0]
        return f"{scheme}://{user}:***@{host}"
    return url


def _run_to_dict(run: Any) -> dict[str, Any]:
    import json

    try:
        failed = json.loads(run.windows_failed_json or "[]")
    except json.JSONDecodeError:  # pragma: no cover - defensive
        failed = []
    return {
        "id": run.id,
        "dataset": run.dataset,
        "source": run.source,
        "range_kind": run.range_kind,
        "range_start": _iso(run.range_start),
        "range_end": _iso(run.range_end),
        "started_at": _iso(run.started_at),
        "finished_at": _iso(run.finished_at),
        "status": run.status,
        "records_retrieved": run.records_retrieved,
        "records_inserted": run.records_inserted,
        "records_updated": run.records_updated,
        "windows_total": run.windows_total,
        "windows_ok": run.windows_ok,
        "windows_failed": failed,
        "error_detail": run.error_detail,
        "coverage_verified": run.coverage_verified,
        "coverage_detail": run.coverage_detail,
    }


def _iso(value: Optional[datetime]) -> Optional[str]:
    aware = _as_utc(value)
    return aware.isoformat() if aware else None
