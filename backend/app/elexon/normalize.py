"""Validation and normalisation of raw Elexon records.

Every record that cannot be used is returned as an :class:`ExcludedRecord`
with an explicit reason so that nothing disappears silently.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from ..models import ActualGeneration, ExcludedRecord, WindForecast

DATASET_ACTUAL = "FUELHH"
DATASET_FORECAST = "WINDFOR"

REASON_INVALID_TIMESTAMP = "invalid_timestamp"
REASON_MISSING_TIMESTAMP = "missing_timestamp"
REASON_INVALID_GENERATION = "invalid_generation_value"
REASON_MISSING_FIELDS = "missing_required_fields"
REASON_NOT_A_RECORD = "malformed_record"
REASON_DUPLICATE_ACTUAL = "duplicate_actual_interval"
REASON_DUPLICATE_FORECAST = "duplicate_forecast_publication"


def parse_timestamp(value: Any) -> datetime:
    """Parse an ISO-8601 timestamp into a timezone-aware UTC datetime.

    Naive timestamps are rejected: comparing naive and aware datetimes would
    silently corrupt the cutoff test.
    """
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value.strip():
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"unparseable timestamp: {value!r}") from exc
    else:
        raise ValueError(f"missing timestamp: {value!r}")

    if dt.tzinfo is None:
        raise ValueError(f"naive timestamp without timezone: {value!r}")
    return dt.astimezone(timezone.utc)


def parse_generation(value: Any) -> float:
    """Parse a generation value, rejecting missing/non-finite/non-numeric data."""
    if isinstance(value, bool) or value is None:
        raise ValueError(f"missing generation value: {value!r}")
    if isinstance(value, str):
        value = value.strip()
        if value == "":
            raise ValueError("missing generation value")
        try:
            value = float(value)
        except ValueError as exc:
            raise ValueError(f"non-numeric generation value: {value!r}") from exc
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        raise ValueError(f"unsupported generation value type: {type(value).__name__}")
    if not math.isfinite(number):
        raise ValueError(f"non-finite generation value: {value!r}")
    return number


def normalize_actual(raw: Any) -> tuple[Optional[ActualGeneration], Optional[ExcludedRecord]]:
    if not isinstance(raw, dict):
        return None, ExcludedRecord(DATASET_ACTUAL, REASON_NOT_A_RECORD, "record is not an object")
    try:
        start = parse_timestamp(raw.get("startTime"))
    except ValueError as exc:
        return None, ExcludedRecord(
            DATASET_ACTUAL,
            REASON_INVALID_TIMESTAMP if raw.get("startTime") else REASON_MISSING_TIMESTAMP,
            str(exc),
            dict(raw),
        )
    try:
        generation = parse_generation(raw.get("generation"))
    except ValueError as exc:
        return None, ExcludedRecord(
            DATASET_ACTUAL, REASON_INVALID_GENERATION, str(exc), dict(raw)
        )

    publish: Optional[datetime] = None
    if raw.get("publishTime"):
        try:
            publish = parse_timestamp(raw.get("publishTime"))
        except ValueError:
            publish = None  # outturn publish time is provenance, not a filter key

    settlement_period = raw.get("settlementPeriod")
    if not isinstance(settlement_period, int):
        settlement_period = None

    return (
        ActualGeneration(
            start_time=start,
            generation_mw=generation,
            publish_time=publish,
            settlement_date=raw.get("settlementDate"),
            settlement_period=settlement_period,
        ),
        None,
    )


def normalize_forecast(raw: Any) -> tuple[Optional[WindForecast], Optional[ExcludedRecord]]:
    if not isinstance(raw, dict):
        return None, ExcludedRecord(DATASET_FORECAST, REASON_NOT_A_RECORD, "record is not an object")
    try:
        start = parse_timestamp(raw.get("startTime"))
    except ValueError as exc:
        return None, ExcludedRecord(
            DATASET_FORECAST,
            REASON_INVALID_TIMESTAMP if raw.get("startTime") else REASON_MISSING_TIMESTAMP,
            str(exc),
            dict(raw),
        )
    try:
        publish = parse_timestamp(raw.get("publishTime"))
    except ValueError as exc:
        return None, ExcludedRecord(
            DATASET_FORECAST,
            REASON_INVALID_TIMESTAMP if raw.get("publishTime") else REASON_MISSING_TIMESTAMP,
            str(exc),
            dict(raw),
        )
    try:
        generation = parse_generation(raw.get("generation"))
    except ValueError as exc:
        return None, ExcludedRecord(
            DATASET_FORECAST, REASON_INVALID_GENERATION, str(exc), dict(raw)
        )
    return WindForecast(start_time=start, publish_time=publish, generation_mw=generation), None


def normalize_collection(
    raw_rows: Iterable[Any], normalizer, dataset: str
) -> tuple[list, list[ExcludedRecord]]:
    """Normalise a collection, collecting every rejected record."""
    records = []
    excluded: list[ExcludedRecord] = []
    for row in raw_rows:
        record, problem = normalizer(row)
        if record is not None:
            records.append(record)
        elif problem is not None:
            excluded.append(problem)
    return records, excluded


def deduplicate_actuals(
    records: list[ActualGeneration],
) -> tuple[list[ActualGeneration], list[ExcludedRecord]]:
    """Collapse repeated delivery intervals.

    Policy: the record carrying the latest source ``publishTime`` wins (latest
    revision), falling back to the greater generation value when the publish
    time is absent or identical.  Rejected duplicates are reported.
    """
    best: dict[datetime, ActualGeneration] = {}
    rejected: list[ExcludedRecord] = []
    for record in records:
        current = best.get(record.start_time)
        if current is None:
            best[record.start_time] = record
            continue
        current_pub = current.publish_time or datetime.min.replace(tzinfo=timezone.utc)
        new_pub = record.publish_time or datetime.min.replace(tzinfo=timezone.utc)
        winner, loser = (
            (record, current) if (new_pub, record.generation_mw) >= (current_pub, current.generation_mw) else (current, record)
        )
        best[record.start_time] = winner
        rejected.append(
            ExcludedRecord(
                DATASET_ACTUAL,
                REASON_DUPLICATE_ACTUAL,
                f"duplicate delivery interval {record.start_time.isoformat()}; kept "
                f"{winner.generation_mw} MW, dropped {loser.generation_mw} MW",
            )
        )
    return sorted(best.values(), key=lambda r: r.start_time), rejected


def deduplicate_forecasts(
    records: list[WindForecast],
) -> tuple[list[WindForecast], list[ExcludedRecord]]:
    """Collapse repeated ``(start_time, publish_time)`` forecast publications.

    Conflicting values for the same publication are resolved deterministically
    by keeping the greatest generation value, and are reported as a data
    quality issue rather than silently averaged.
    """
    best: dict[tuple[datetime, datetime], WindForecast] = {}
    rejected: list[ExcludedRecord] = []
    for record in records:
        key = (record.start_time, record.publish_time)
        current = best.get(key)
        if current is None:
            best[key] = record
            continue
        winner, loser = (
            (record, current) if record.generation_mw >= current.generation_mw else (current, record)
        )
        best[key] = winner
        rejected.append(
            ExcludedRecord(
                DATASET_FORECAST,
                REASON_DUPLICATE_FORECAST,
                f"conflicting values for startTime={record.start_time.isoformat()} "
                f"publishTime={record.publish_time.isoformat()}; kept {winner.generation_mw} MW, "
                f"dropped {loser.generation_mw} MW",
            )
        )
    ordered = sorted(best.values(), key=lambda r: (r.start_time, r.publish_time))
    return ordered, rejected
