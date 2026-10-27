"""Forecast/actual matching on the delivery interval."""

from __future__ import annotations

from datetime import datetime, timezone

from app.analysis.matching import build_observations
from app.analysis.selection import SelectionOutcome, select_latest_eligible
from app.models import ActualGeneration, WindForecast

UTC = timezone.utc


def ts(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def make_selection(interval: str, publish: str | None, cutoff: str):
    candidates = (
        [
            WindForecast(
                start_time=ts(interval), publish_time=ts(publish), generation_mw=9500
            )
        ]
        if publish
        else []
    )
    return select_latest_eligible(candidates, ts(cutoff), ts(interval))


def test_matched_interval_computes_signed_error():
    interval = "2026-01-15T10:00:00"
    selections = {ts(interval): make_selection(interval, "2026-01-14T11:30:00", "2026-01-14T12:00:00")}
    actuals = {
        ts(interval): ActualGeneration(start_time=ts(interval), generation_mw=8000)
    }
    (obs,) = build_observations([ts(interval)], selections, actuals)
    assert obs.status == "matched"
    assert obs.error_mw == 1500.0  # overforecast
    assert obs.absolute_error_mw == 1500.0
    assert obs.squared_error_mw2 == 2_250_000.0
    assert obs.selected_publish_time == ts("2026-01-14T11:30:00")


def test_negative_error_means_underforecast():
    interval = "2026-01-15T10:00:00"
    selections = {ts(interval): make_selection(interval, "2026-01-14T11:30:00", "2026-01-14T12:00:00")}
    actuals = {
        ts(interval): ActualGeneration(start_time=ts(interval), generation_mw=12000)
    }
    (obs,) = build_observations([ts(interval)], selections, actuals)
    assert obs.error_mw == -2500.0
    assert obs.status == "matched"


def test_missing_actual_is_reported_not_zeroed():
    interval = "2026-01-15T10:00:00"
    selections = {ts(interval): make_selection(interval, "2026-01-14T11:30:00", "2026-01-14T12:00:00")}
    (obs,) = build_observations([ts(interval)], selections, {})
    assert obs.status == "missing_actual"
    assert obs.actual_mw is None
    assert obs.error_mw is None
    assert obs.forecast_mw == 9500.0


def test_missing_forecast_is_reported_with_a_reason():
    interval = "2026-01-15T10:00:00"
    selections = {ts(interval): make_selection(interval, None, "2026-01-14T12:00:00")}
    actuals = {
        ts(interval): ActualGeneration(start_time=ts(interval), generation_mw=8000)
    }
    (obs,) = build_observations([ts(interval)], selections, actuals)
    assert obs.status == "missing_eligible_forecast"
    assert obs.forecast_mw is None
    assert obs.exclusion_reason == "no_forecast_published_for_interval"


def test_matching_uses_delivery_interval_not_publish_time():
    interval = "2026-01-15T10:00:00"
    other = "2026-01-15T11:00:00"
    selections = {ts(interval): make_selection(interval, "2026-01-14T11:30:00", "2026-01-14T12:00:00")}
    # Actual exists only for a *different* interval -> must not be borrowed.
    actuals = {ts(other): ActualGeneration(start_time=ts(other), generation_mw=8000)}
    (obs,) = build_observations([ts(interval)], selections, actuals)
    assert obs.status == "missing_actual"


def test_hourly_forecast_source_interval_is_carried():
    """A half-hourly interval inherits the forecast of its containing hour."""
    hour = "2026-01-15T10:00:00"
    half_hour = "2026-01-15T10:30:00"
    selections = {
        ts(hour): make_selection(hour, "2026-01-14T11:30:00", "2026-01-14T12:00:00")
    }
    actuals = {
        ts(half_hour): ActualGeneration(start_time=ts(half_hour), generation_mw=8000)
    }
    (obs,) = build_observations([ts(half_hour)], selections, actuals)
    assert obs.status == "matched"
    assert obs.forecast_mw == 9500.0
    assert obs.forecast_source_start == ts(hour)


def test_mean_of_two_half_hour_errors_equals_the_hourly_error():
    """The hourly-to-half-hourly broadcast is energy conserving."""
    hour = "2026-01-15T10:00:00"
    first = "2026-01-15T10:00:00"
    second = "2026-01-15T10:30:00"
    selections = {
        ts(first): make_selection(first, "2026-01-14T11:30:00", "2026-01-14T12:00:00"),
        ts(second): make_selection(second, "2026-01-14T11:30:00", "2026-01-14T12:00:00"),
    }
    actuals = {
        ts(first): ActualGeneration(start_time=ts(first), generation_mw=9000),
        ts(second): ActualGeneration(start_time=ts(second), generation_mw=7000),
    }
    obs = build_observations([ts(first), ts(second)], selections, actuals)
    hourly_actual_mean = (9000 + 7000) / 2
    hourly_error = 9500 - hourly_actual_mean
    mean_half_hour_error = sum(o.error_mw for o in obs) / 2
    assert mean_half_hour_error == hourly_error
    assert hour == "2026-01-15T10:00:00"
