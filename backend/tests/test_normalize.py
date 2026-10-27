"""Normalisation: malformed records, duplicates and exclusion reasons."""

from __future__ import annotations

from datetime import datetime, timezone

from app.elexon.normalize import (
    REASON_DUPLICATE_ACTUAL,
    REASON_DUPLICATE_FORECAST,
    REASON_INVALID_GENERATION,
    REASON_INVALID_TIMESTAMP,
    deduplicate_actuals,
    deduplicate_forecasts,
    normalize_actual,
    normalize_forecast,
    parse_generation,
    parse_timestamp,
)

import pytest


def test_parses_iso_timestamps_to_utc():
    parsed = parse_timestamp("2026-01-15T11:30:00Z")
    assert parsed.tzinfo is not None
    assert parsed.utcoffset().total_seconds() == 0
    # An offset timestamp is a different instant unless it denotes the same one.
    assert parse_timestamp("2026-01-15T12:30:00+01:00") == parsed
    assert parse_timestamp("2026-01-15T11:30:00+01:00") != parsed


def test_rejects_naive_timestamps():
    with pytest.raises(ValueError):
        parse_timestamp("2026-01-15T11:30:00")
    with pytest.raises(ValueError):
        parse_timestamp("not-a-date")
    with pytest.raises(ValueError):
        parse_timestamp(None)


def test_rejects_invalid_generation_values():
    assert parse_generation(1234) == 1234.0
    assert parse_generation("1234.5") == 1234.5
    for bad in (None, "", "abc", float("nan"), float("inf"), True):
        with pytest.raises(ValueError):
            parse_generation(bad)


def test_normalize_actual_reports_bad_records():
    good, problem = normalize_actual(
        {
            "startTime": "2026-01-01T00:00:00Z",
            "publishTime": "2026-01-01T00:30:00Z",
            "generation": 12345,
            "settlementPeriod": 1,
        }
    )
    assert problem is None
    assert good.generation_mw == 12345.0
    assert good.settlement_period == 1

    record, problem = normalize_actual({"startTime": "rubbish", "generation": 1})
    assert record is None
    assert problem.reason == REASON_INVALID_TIMESTAMP

    record, problem = normalize_actual({"startTime": "2026-01-01T00:00:00Z", "generation": None})
    assert record is None
    assert problem.reason == REASON_INVALID_GENERATION

    record, problem = normalize_actual("not an object")
    assert record is None and problem is not None


def test_normalize_forecast_keeps_publish_and_start_distinct():
    record, problem = normalize_forecast(
        {
            "startTime": "2026-01-15T10:00:00Z",
            "publishTime": "2026-01-14T11:30:00Z",
            "generation": 9500,
        }
    )
    assert problem is None
    assert record.start_time != record.publish_time
    assert record.publish_time < record.start_time


def test_duplicate_actuals_keep_the_latest_revision():
    older = {
        "startTime": "2026-01-01T00:00:00Z",
        "publishTime": "2026-01-01T00:30:00Z",
        "generation": 100,
    }
    newer = {
        "startTime": "2026-01-01T00:00:00Z",
        "publishTime": "2026-01-02T00:30:00Z",
        "generation": 120,
    }
    a1, _ = normalize_actual(older)
    a2, _ = normalize_actual(newer)
    kept, rejected = deduplicate_actuals([a1, a2])
    assert len(kept) == 1
    assert kept[0].generation_mw == 120
    assert rejected[0].reason == REASON_DUPLICATE_ACTUAL


def test_duplicate_forecasts_with_conflicting_values_are_reported():
    f1, _ = normalize_forecast(
        {"startTime": "2026-01-01T10:00:00Z", "publishTime": "2026-01-01T09:00:00Z", "generation": 500}
    )
    f2, _ = normalize_forecast(
        {"startTime": "2026-01-01T10:00:00Z", "publishTime": "2026-01-01T09:00:00Z", "generation": 700}
    )
    kept, rejected = deduplicate_forecasts([f1, f2])
    assert len(kept) == 1
    assert kept[0].generation_mw == 700
    assert rejected[0].reason == REASON_DUPLICATE_FORECAST
    # Deterministic regardless of input order.
    kept2, _ = deduplicate_forecasts([f2, f1])
    assert kept2[0].generation_mw == 700


def test_exact_duplicates_do_not_grow_the_dataset():
    row = {"startTime": "2026-01-01T10:00:00Z", "publishTime": "2026-01-01T09:00:00Z", "generation": 500}
    f1, _ = normalize_forecast(row)
    f2, _ = normalize_forecast(dict(row))
    kept, _ = deduplicate_forecasts([f1, f2])
    assert len(kept) == 1


def test_timestamps_compare_as_aware_datetimes():
    f1, _ = normalize_forecast(
        {"startTime": "2026-01-01T10:00:00Z", "publishTime": "2026-01-01T09:00:00Z", "generation": 1}
    )
    assert f1.publish_time <= datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
