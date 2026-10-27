"""Repository: the only place that reads or writes observation tables.

Idempotency rules (verified against the source schemas):

* **Actuals (FUELHH)** - natural key ``(dataset, start_time)``.  A re-import of
  the same value is a no-op; a later ``publishTime`` replaces the stored row
  (Elexon revision), an older one never does.
* **Forecasts (WINDFOR)** - natural key ``(dataset, start_time, publish_time)``.
  Publication versions are never merged, so historical cutoff reconstruction
  stays exact no matter how often an import is repeated.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Iterable, Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import ActualGeneration, WindForecast
from .models import ActualGenerationRow, DataImportRun, WindForecastRow, utcnow

UTC = timezone.utc


def as_utc(value: Optional[datetime]) -> Optional[datetime]:
    """Coerce a driver value into a timezone-aware UTC instant."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@dataclass
class UpsertCounts:
    inserted: int = 0
    updated: int = 0
    skipped: int = 0

    @property
    def written(self) -> int:
        return self.inserted + self.updated


# --------------------------------------------------------------------------- #
# Upserts
# --------------------------------------------------------------------------- #
def upsert_actuals(
    session: Session,
    records: Iterable[ActualGeneration],
    *,
    retrieved_at: Optional[datetime] = None,
) -> UpsertCounts:
    """Insert or revision-update actual outturn records."""
    retrieved_at = retrieved_at or utcnow()
    counts = UpsertCounts()

    for record in records:
        existing = session.execute(
            select(ActualGenerationRow).where(
                ActualGenerationRow.dataset == record.source,
                ActualGenerationRow.start_time == record.start_time,
            )
        ).scalar_one_or_none()

        if existing is None:
            session.add(
                ActualGenerationRow(
                    dataset=record.source,
                    start_time=record.start_time,
                    generation_mw=record.generation_mw,
                    publish_time=record.publish_time,
                    settlement_date=record.settlement_date,
                    settlement_period=record.settlement_period,
                    retrieved_at=retrieved_at,
                )
            )
            counts.inserted += 1
            continue

        incoming_publish = record.publish_time or datetime.min.replace(tzinfo=UTC)
        current_publish = as_utc(existing.publish_time) or datetime.min.replace(tzinfo=UTC)
        if incoming_publish < current_publish:
            counts.skipped += 1  # older revision: keep what we already have
            continue

        existing.generation_mw = record.generation_mw
        existing.publish_time = record.publish_time
        existing.settlement_date = record.settlement_date
        existing.settlement_period = record.settlement_period
        existing.retrieved_at = retrieved_at
        counts.updated += 1

    return counts


def upsert_forecasts(
    session: Session,
    records: Iterable[WindForecast],
    *,
    retrieved_at: Optional[datetime] = None,
) -> UpsertCounts:
    """Insert forecast publications; distinct publication versions are kept."""
    retrieved_at = retrieved_at or utcnow()
    counts = UpsertCounts()

    for record in records:
        existing = session.execute(
            select(WindForecastRow).where(
                WindForecastRow.dataset == record.source,
                WindForecastRow.start_time == record.start_time,
                WindForecastRow.publish_time == record.publish_time,
            )
        ).scalar_one_or_none()

        if existing is None:
            session.add(
                WindForecastRow(
                    dataset=record.source,
                    start_time=record.start_time,
                    publish_time=record.publish_time,
                    generation_mw=record.generation_mw,
                    retrieved_at=retrieved_at,
                )
            )
            counts.inserted += 1
            continue

        if existing.generation_mw != record.generation_mw:
            # Same publication re-issued with a corrected value: keep the latest
            # retrieved value and record the update rather than duplicating.
            existing.generation_mw = record.generation_mw
            existing.retrieved_at = retrieved_at
            counts.updated += 1
        else:
            counts.skipped += 1

    return counts


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #
def load_actuals(session: Session) -> list[ActualGeneration]:
    rows = session.execute(
        select(ActualGenerationRow).order_by(ActualGenerationRow.start_time)
    ).scalars()
    return [
        ActualGeneration(
            start_time=as_utc(row.start_time),
            generation_mw=row.generation_mw,
            publish_time=as_utc(row.publish_time),
            settlement_date=row.settlement_date,
            settlement_period=row.settlement_period,
            source=row.dataset,
        )
        for row in rows
    ]


def load_forecasts(session: Session) -> list[WindForecast]:
    rows = session.execute(
        select(WindForecastRow).order_by(
            WindForecastRow.start_time, WindForecastRow.publish_time
        )
    ).scalars()
    return [
        WindForecast(
            start_time=as_utc(row.start_time),
            publish_time=as_utc(row.publish_time),
            generation_mw=row.generation_mw,
            source=row.dataset,
        )
        for row in rows
    ]


def count_actuals(session: Session) -> int:
    return int(
        session.execute(select(func.count(ActualGenerationRow.id))).scalar_one()
    )


def count_forecasts(session: Session) -> int:
    return int(
        session.execute(select(func.count(WindForecastRow.id))).scalar_one()
    )


def forecast_publication_range(session: Session) -> tuple[Optional[datetime], Optional[datetime]]:
    low = session.execute(select(func.min(WindForecastRow.publish_time))).scalar_one_or_none()
    high = session.execute(select(func.max(WindForecastRow.publish_time))).scalar_one_or_none()
    return as_utc(low), as_utc(high)


def distinct_delivery_dates(session: Session, dataset: str = "FUELHH") -> int:
    """Number of distinct local delivery dates present for an actual dataset."""
    rows = session.execute(
        select(ActualGenerationRow.start_time).where(ActualGenerationRow.dataset == dataset)
    ).scalars()
    return len({as_utc(value).astimezone(UTC).date() for value in rows})


def forecast_interval_count(session: Session) -> int:
    """Distinct delivery intervals that carry at least one forecast."""
    return int(
        session.execute(
            select(func.count(func.distinct(WindForecastRow.start_time)))
        ).scalar_one()
    )


# --------------------------------------------------------------------------- #
# Import runs
# --------------------------------------------------------------------------- #
def record_import_start(
    session: Session,
    *,
    dataset: str,
    range_start: datetime,
    range_end: datetime,
    source: str = "elexon_live",
    range_kind: str = "delivery",
) -> DataImportRun:
    run = DataImportRun(
        dataset=dataset,
        source=source,
        range_kind=range_kind,
        range_start=range_start,
        range_end=range_end,
        started_at=utcnow(),
        status="running",
    )
    session.add(run)
    session.flush()
    return run


def record_import_finish(
    session: Session,
    run: DataImportRun,
    *,
    status: str,
    records_retrieved: int = 0,
    records_inserted: int = 0,
    records_updated: int = 0,
    windows_total: int = 0,
    windows_ok: int = 0,
    windows_failed: Sequence[str] = (),
    error_detail: Optional[str] = None,
    coverage_verified: bool = False,
    coverage_detail: Optional[str] = None,
) -> DataImportRun:
    run.finished_at = utcnow()
    run.status = status
    run.records_retrieved = records_retrieved
    run.records_inserted = records_inserted
    run.records_updated = records_updated
    run.windows_total = windows_total
    run.windows_ok = windows_ok
    run.windows_failed_json = _dumps(list(windows_failed))
    run.error_detail = error_detail
    run.coverage_verified = coverage_verified
    run.coverage_detail = coverage_detail
    session.add(run)
    session.flush()
    return run


def latest_imports(session: Session, dataset: Optional[str] = None, limit: int = 10) -> list[DataImportRun]:
    statement = select(DataImportRun).order_by(DataImportRun.started_at.desc()).limit(limit)
    if dataset:
        statement = statement.where(DataImportRun.dataset == dataset)
    return list(session.execute(statement).scalars())


def latest_successful_import(session: Session, dataset: str) -> Optional[DataImportRun]:
    statement = (
        select(DataImportRun)
        .where(DataImportRun.dataset == dataset, DataImportRun.status == "completed")
        .order_by(DataImportRun.finished_at.desc())
        .limit(1)
    )
    return session.execute(statement).scalar_one_or_none()


def has_running_import(session: Session, dataset: str) -> bool:
    row = session.execute(
        select(DataImportRun.id)
        .where(DataImportRun.dataset == dataset, DataImportRun.status == "running")
        .limit(1)
    ).first()
    return row is not None


def coverage_snapshot(session: Session, date_from: date, date_to: date) -> dict:
    """Actual-interval coverage for a delivery-date range."""
    rows = session.execute(
        select(ActualGenerationRow.start_time).where(ActualGenerationRow.dataset == "FUELHH")
    ).scalars()
    wanted = set()
    present = set()
    day = date_from
    from datetime import timedelta

    while day <= date_to:
        for hour in range(24):
            for minute in (0, 30):
                wanted.add(day.isoformat() + f"T{hour:02d}:{minute:02d}")
        day += timedelta(days=1)

    for value in rows:
        instant = as_utc(value)
        present.add(instant.strftime("%Y-%m-%dT%H:%M"))

    return {
        "expected": len(wanted),
        "present": len(wanted & present),
        "missing": sorted(wanted - present)[:20],
    }


def _dumps(value: object) -> str:
    import json

    return json.dumps(value)
