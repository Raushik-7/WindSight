"""Durable import of Elexon history into the database.

Responsibilities
----------------
* retrieve records in bounded windows (live API or committed snapshot),
* validate and normalise them with the existing rules,
* write them idempotently (see :mod:`app.db.repository`),
* record a ``data_import_runs`` audit row per dataset and per import attempt,
* verify that the requested coverage is actually present - a run whose HTTP
  requests all succeeded but whose data has gaps is ``partial``, never
  ``completed``.

The importer never fabricates data: a failed window stays failed and is
reported.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from .analysis.calendar import INTERVALS_PER_DAY, hour_floor
from .analysis.selection import build_forecast_index, select_latest_eligible
from .config import Settings
from .db import repository
from .db.models import DataImportRun, utcnow
from .elexon.client import ElexonClient, UpstreamError, date_windows
from .elexon.normalize import (
    deduplicate_actuals,
    deduplicate_forecasts,
    normalize_collection,
    normalize_actual,
    normalize_forecast,
)

logger = logging.getLogger(__name__)

UTC = timezone.utc

DATASET_ACTUALS = "fuelhh"
DATASET_FORECASTS = "windfor"

STATUS_COMPLETED = "completed"
STATUS_PARTIAL = "partial"
STATUS_FAILED = "failed"


@dataclass
class DatasetImportResult:
    """Outcome of importing one dataset for one requested range."""

    dataset: str
    source: str
    status: str
    range_start: datetime
    range_end: datetime
    records_retrieved: int = 0
    records_inserted: int = 0
    records_updated: int = 0
    records_skipped: int = 0
    windows_total: int = 0
    windows_ok: int = 0
    windows_failed: list[str] = field(default_factory=list)
    coverage_verified: bool = False
    coverage_detail: str = ""
    error_detail: Optional[str] = None
    run_id: Optional[int] = None

    @property
    def ok(self) -> bool:
        return self.status == STATUS_COMPLETED


# --------------------------------------------------------------------------- #
# Snapshot reader (offline seeding / demos)
# --------------------------------------------------------------------------- #
def read_snapshot(path: Path) -> list[dict]:
    """Read a committed snapshot payload written by scripts/fetch_snapshots.py."""
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("rows") if isinstance(payload, dict) else None
    return rows if isinstance(rows, list) else []


# --------------------------------------------------------------------------- #
# Import implementations
# --------------------------------------------------------------------------- #
def import_actuals(
    session: Session,
    settings: Settings,
    *,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    client: Optional[ElexonClient] = None,
    source: str = "elexon_live",
) -> DatasetImportResult:
    """Import FUELHH WIND outturn for a delivery-date range."""
    date_from = date_from or settings.eval_start
    date_to = date_to or settings.eval_end
    range_start = datetime.combine(date_from, datetime.min.time(), tzinfo=UTC)
    range_end = datetime.combine(date_to, datetime.min.time(), tzinfo=UTC) + timedelta(
        hours=23, minutes=59
    )

    run = repository.record_import_start(
        session,
        dataset="FUELHH",
        range_start=range_start,
        range_end=range_end,
        source=source,
        range_kind="delivery",
    )
    session.commit()
    result = DatasetImportResult(
        dataset="FUELHH",
        source=source,
        status=STATUS_RUNNING_PLACEHOLDER,
        range_start=range_start,
        range_end=range_end,
        run_id=run.id,
    )

    windows = date_windows(date_from, date_to, settings.elexon_window_days)
    result.windows_total = len(windows)

    try:
        if source == "snapshot":
            rows = read_snapshot(settings.snapshot_dir / "fuelhh.json")
            raw_by_window: list[tuple[str, list[dict]]] = [("snapshot", rows)]
        else:
            owns_client = client is None
            active = client or ElexonClient(
                settings.elexon_base_url,
                timeout=settings.elexon_timeout_seconds,
                max_retries=settings.elexon_max_retries,
                backoff_seconds=settings.elexon_backoff_seconds,
                window_days=settings.elexon_window_days,
            )
            try:
                raw_by_window = []
                for window_start, window_end in windows:
                    label = f"{window_start.isoformat()}..{window_end.isoformat()}"
                    try:
                        raw_by_window.append(
                            (
                                label,
                                active.fetch_actuals(window_start, window_end),
                            )
                        )
                    except UpstreamError as exc:
                        result.windows_failed.append(f"{label}: {exc}")
                        logger.warning("FUELHH window failed: %s", exc)
            finally:
                if owns_client:
                    active.close()
    except Exception as exc:  # pragma: no cover - defensive
        result.error_detail = str(exc)
        _finish(session, run, result)
        return result

    records, exclusions = normalize_collection(
        [row for _, rows in raw_by_window for row in rows], normalize_actual, "FUELHH"
    )
    records, duplicates = deduplicate_actuals(records)

    retrieved_at = utcnow()
    counts = repository.upsert_actuals(session, records, retrieved_at=retrieved_at)
    session.commit()

    result.records_retrieved = sum(len(rows) for _, rows in raw_by_window)
    result.records_inserted = counts.inserted
    result.records_updated = counts.updated
    result.records_skipped = counts.skipped + len(exclusions) + len(duplicates)
    result.windows_ok = len(raw_by_window)
    if source == "snapshot":
        # A snapshot is a single retrieval unit covering the whole range; do not
        # report "1/3 windows" for an import whose coverage is fully verified.
        result.windows_total = len(raw_by_window)

    coverage = repository.coverage_snapshot(session, date_from, date_to)
    expected = INTERVALS_PER_DAY * ((date_to - date_from).days + 1)
    result.coverage_verified = coverage["present"] == expected and not result.windows_failed
    result.coverage_detail = (
        f"{coverage['present']}/{expected} half-hourly delivery intervals present "
        f"({len(exclusions)} malformed, {len(duplicates)} duplicate revisions)"
    )
    _finish(session, run, result)
    return result


def import_forecasts(
    session: Session,
    settings: Settings,
    *,
    publish_from: Optional[datetime] = None,
    publish_to: Optional[datetime] = None,
    client: Optional[ElexonClient] = None,
    source: str = "elexon_live",
) -> DatasetImportResult:
    """Import WINDFOR publications for a *publication*-time range."""
    publish_from = publish_from or (
        datetime.combine(
            settings.eval_start - timedelta(days=settings.forecast_history_days),
            datetime.min.time(),
            tzinfo=UTC,
        )
    )
    publish_to = publish_to or (
        datetime.combine(settings.eval_end + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
        - timedelta(seconds=1)
    )

    run = repository.record_import_start(
        session,
        dataset="WINDFOR",
        range_start=publish_from,
        range_end=publish_to,
        source=source,
        range_kind="publication",
    )
    session.commit()
    result = DatasetImportResult(
        dataset="WINDFOR",
        source=source,
        status=STATUS_RUNNING_PLACEHOLDER,
        range_start=publish_from,
        range_end=publish_to,
        run_id=run.id,
    )

    step = timedelta(days=settings.elexon_window_days)
    windows: list[tuple[datetime, datetime]] = []
    cursor = publish_from
    while cursor <= publish_to:
        window_end = min(cursor + step, publish_to)
        windows.append((cursor, window_end))
        cursor = window_end + timedelta(seconds=1)
    result.windows_total = len(windows)

    try:
        if source == "snapshot":
            rows = read_snapshot(settings.snapshot_dir / "windfor.json")
            raw_by_window: list[tuple[str, list[dict]]] = [("snapshot", rows)]
        else:
            owns_client = client is None
            active = client or ElexonClient(
                settings.elexon_base_url,
                timeout=settings.elexon_timeout_seconds,
                max_retries=settings.elexon_max_retries,
                backoff_seconds=settings.elexon_backoff_seconds,
                window_days=settings.elexon_window_days,
            )
            try:
                raw_by_window = []
                for window_start, window_end in windows:
                    label = f"{window_start.date().isoformat()}..{window_end.date().isoformat()}"
                    try:
                        raw_by_window.append(
                            (label, active.fetch_forecasts(window_start, window_end))
                        )
                    except UpstreamError as exc:
                        result.windows_failed.append(f"{label}: {exc}")
                        logger.warning("WINDFOR window failed: %s", exc)
            finally:
                if owns_client:
                    active.close()
    except Exception as exc:  # pragma: no cover - defensive
        result.error_detail = str(exc)
        _finish(session, run, result)
        return result

    records, exclusions = normalize_collection(
        [row for _, rows in raw_by_window for row in rows], normalize_forecast, "WINDFOR"
    )
    records, duplicates = deduplicate_forecasts(records)

    counts = repository.upsert_forecasts(session, records, retrieved_at=utcnow())
    session.commit()

    result.records_retrieved = sum(len(rows) for _, rows in raw_by_window)
    result.records_inserted = counts.inserted
    result.records_updated = counts.updated
    result.records_skipped = counts.skipped + len(exclusions) + len(duplicates)
    result.windows_ok = len(raw_by_window)
    if source == "snapshot":
        # See import_actuals: one snapshot retrieval covers every window.
        result.windows_total = len(raw_by_window)

    verified, detail = verify_forecast_coverage(session, settings)
    result.coverage_verified = verified and not result.windows_failed
    result.coverage_detail = detail
    _finish(session, run, result)
    return result


def verify_forecast_coverage(session: Session, settings: Settings) -> tuple[bool, str]:
    """Every evaluation delivery interval must have an eligible forecast.

    This is the check that turns an HTTP-successful import into an honestly
    labelled one: we rebuild the selection index from what is actually stored
    and count intervals that would come out empty under the default cutoff.
    """
    from .analysis.calendar import build_delivery_intervals

    forecasts = repository.load_forecasts(session)
    intervals = build_delivery_intervals(
        settings.eval_start, settings.eval_end, settings.tz
    )
    index = build_forecast_index(forecasts)

    missing = 0
    for start in intervals:
        delivery_date = start.astimezone(settings.tz).date()
        cutoff = (
            datetime.combine(
                delivery_date + timedelta(days=settings.cutoff_day_offset),
                settings.cutoff_time,
                tzinfo=settings.tz,
            )
            .astimezone(UTC)
        )
        hour_key = hour_floor(start)
        candidates = index.get(hour_key) or index.get(start) or []
        outcome = select_latest_eligible(candidates, cutoff, start)
        if outcome.selected is None:
            missing += 1

    detail = (
        f"{len(intervals) - missing}/{len(intervals)} delivery intervals have an "
        f"eligible forecast under the {settings.cutoff_time.strftime('%H:%M')} "
        f"{settings.business_timezone} cutoff"
    )
    return missing == 0, detail


# --------------------------------------------------------------------------- #
# Convenience entry points
# --------------------------------------------------------------------------- #
STATUS_RUNNING_PLACEHOLDER = "running"


def import_evaluation_period(
    session: Session,
    settings: Settings,
    *,
    source: str = "elexon_live",
    client: Optional[ElexonClient] = None,
) -> list[DatasetImportResult]:
    """Import both datasets for the configured evaluation period."""
    actual_result = import_actuals(
        session, settings, source=source, client=client
    )
    forecast_result = import_forecasts(
        session, settings, source=source, client=client
    )
    return [actual_result, forecast_result]


def seed_from_snapshots(session: Session, settings: Settings) -> list[DatasetImportResult]:
    """First-run seeding from the committed real-data snapshots (offline)."""
    return import_evaluation_period(session, settings, source="snapshot")


def ensure_history(
    session: Session,
    settings: Settings,
    *,
    seed_if_missing: bool = True,
) -> tuple[bool, str]:
    """Startup guard: make sure durable data exists before serving analytics.

    Returns ``(ready, message)``.  When the database is empty and seeding is
    allowed, the committed snapshot is imported once and recorded as an import
    run with ``source='snapshot'``.
    """
    expected = INTERVALS_PER_DAY * ((settings.eval_end - settings.eval_start).days + 1)
    actual_count = repository.count_actuals(session)
    forecast_count = repository.count_forecasts(session)

    if actual_count >= expected and forecast_count > 0:
        return True, f"{actual_count} actual and {forecast_count} forecast records available"

    if not seed_if_missing:
        return False, (
            f"database holds {actual_count} actual / {forecast_count} forecast records; "
            "run the historical import before serving analytics"
        )

    logger.info("Database is empty - seeding durable storage from committed snapshots")
    results = seed_from_snapshots(session, settings)
    failures = [r for r in results if not r.ok]
    if failures:
        detail = "; ".join(f"{r.dataset}: {r.status} ({r.error_detail})" for r in failures)
        return False, f"snapshot seeding incomplete: {detail}"

    return True, "initial import completed from committed snapshots"


def refresh(
    session: Session,
    settings: Settings,
    *,
    source: str = "elexon_live",
) -> list[DatasetImportResult]:
    """Controlled operator refresh (guarded at the API boundary)."""
    if repository.has_running_import(session, "FUELHH") or repository.has_running_import(
        session, "WINDFOR"
    ):
        raise RuntimeError("An import is already running; refusing to start another.")
    return import_evaluation_period(session, settings, source=source)


def _finish(
    session: Session,
    run: DataImportRun,
    result: DatasetImportResult,
) -> None:
    """Persist the run outcome and mirror it onto the result."""
    if result.status == STATUS_RUNNING_PLACEHOLDER:
        if result.windows_failed and result.windows_ok == 0:
            result.status = STATUS_FAILED
        elif result.windows_failed or not result.coverage_verified:
            result.status = STATUS_PARTIAL
        else:
            result.status = STATUS_COMPLETED

    repository.record_import_finish(
        session,
        run,
        status=result.status,
        records_retrieved=result.records_retrieved,
        records_inserted=result.records_inserted,
        records_updated=result.records_updated,
        windows_total=result.windows_total,
        windows_ok=result.windows_ok,
        windows_failed=result.windows_failed,
        error_detail=result.error_detail,
        coverage_verified=result.coverage_verified,
        coverage_detail=result.coverage_detail,
    )
    session.commit()
    logger.info(
        "Import %s finished: dataset=%s status=%s inserted=%s updated=%s windows=%s/%s coverage=%s",
        run.id,
        result.dataset,
        result.status,
        result.records_inserted,
        result.records_updated,
        result.windows_ok,
        result.windows_total,
        result.coverage_verified,
    )


def result_to_dict(result: DatasetImportResult) -> dict:
    return {
        "dataset": result.dataset,
        "source": result.source,
        "status": result.status,
        "range_start": result.range_start.isoformat(),
        "range_end": result.range_end.isoformat(),
        "records_retrieved": result.records_retrieved,
        "records_inserted": result.records_inserted,
        "records_updated": result.records_updated,
        "records_skipped": result.records_skipped,
        "windows_total": result.windows_total,
        "windows_ok": result.windows_ok,
        "windows_failed": result.windows_failed,
        "coverage_verified": result.coverage_verified,
        "coverage_detail": result.coverage_detail,
        "error_detail": result.error_detail,
        "run_id": result.run_id,
    }
