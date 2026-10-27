"""Forecast selection: the cutoff rule, ties and failure modes."""

from __future__ import annotations

from datetime import datetime, timezone

from app.analysis.selection import (
    build_forecast_index,
    is_eligible,
    select_for_intervals,
    select_latest_eligible,
)
from app.models import WindForecast

UTC = timezone.utc


def ts(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def forecast(start: str, publish: str, mw: float) -> WindForecast:
    return WindForecast(
        start_time=ts(start), publish_time=ts(publish), generation_mw=mw
    )


INTERVAL = "2026-01-15T10:00:00+00:00"
CUTOFF = ts("2026-01-14T12:00:00")


def test_selects_latest_publication_at_or_before_cutoff():
    candidates = [
        forecast(INTERVAL, "2026-01-13T11:30:00", 9000),
        forecast(INTERVAL, "2026-01-14T09:30:00", 9200),
        forecast(INTERVAL, "2026-01-14T11:30:00", 9500),
    ]
    outcome = select_latest_eligible(candidates, CUTOFF, ts(INTERVAL))
    assert outcome.selected is not None
    assert outcome.selected.publish_time == ts("2026-01-14T11:30:00")
    assert outcome.selected.generation_mw == 9500
    assert outcome.eligible_count == 3
    assert outcome.excluded_after_cutoff == 0


def test_excludes_forecasts_published_after_cutoff():
    candidates = [
        forecast(INTERVAL, "2026-01-14T11:30:00", 9500),
        forecast(INTERVAL, "2026-01-14T13:00:00", 9900),
        forecast(INTERVAL, "2026-01-15T01:30:00", 12000),
    ]
    outcome = select_latest_eligible(candidates, CUTOFF, ts(INTERVAL))
    assert outcome.selected is not None
    assert outcome.selected.generation_mw == 9500
    assert outcome.excluded_after_cutoff == 2
    assert outcome.latest_candidate.generation_mw == 12000


def test_publication_exactly_at_cutoff_is_eligible():
    candidates = [forecast(INTERVAL, "2026-01-14T12:00:00", 9700)]
    outcome = select_latest_eligible(candidates, CUTOFF, ts(INTERVAL))
    assert outcome.selected is not None
    assert outcome.selected.generation_mw == 9700
    assert is_eligible(ts("2026-01-14T12:00:00"), CUTOFF)


def test_no_eligible_forecast_when_all_are_late():
    candidates = [
        forecast(INTERVAL, "2026-01-14T12:30:00", 9900),
        forecast(INTERVAL, "2026-01-15T01:30:00", 12000),
    ]
    outcome = select_latest_eligible(candidates, CUTOFF, ts(INTERVAL))
    assert outcome.selected is None
    assert outcome.excluded_reason == "all_forecasts_published_after_cutoff"
    assert outcome.latest_candidate.generation_mw == 12000


def test_no_candidates_at_all():
    outcome = select_latest_eligible([], CUTOFF, ts(INTERVAL))
    assert outcome.selected is None
    assert outcome.excluded_reason == "no_forecast_published_for_interval"


def test_identical_publication_times_break_ties_deterministically():
    same_time = "2026-01-14T11:30:00"
    a = forecast(INTERVAL, same_time, 9100)
    b = forecast(INTERVAL, same_time, 9300)
    forward = select_latest_eligible([a, b], CUTOFF, ts(INTERVAL))
    reverse = select_latest_eligible([b, a], CUTOFF, ts(INTERVAL))
    assert forward.selected.generation_mw == reverse.selected.generation_mw == 9300


def test_timezone_aware_and_naive_boundaries_are_not_mixed():
    candidates = [forecast(INTERVAL, "2026-01-14T11:30:00", 9500)]
    # A cutoff expressed for 12:00 London on 14 Jan equals 12:00 UTC in January.
    london_cutoff = datetime(2026, 1, 14, 12, 0, tzinfo=timezone.utc)
    outcome = select_latest_eligible(candidates, london_cutoff, ts(INTERVAL))
    assert outcome.selected is not None
    # An earlier cutoff in another timezone excludes the same instant correctly.
    earlier = datetime(2026, 1, 14, 10, 0, tzinfo=timezone.utc)
    outcome2 = select_latest_eligible(candidates, earlier, ts(INTERVAL))
    assert outcome2.selected is None


def test_select_for_intervals_applies_the_cutoff_per_delivery_date():
    index = build_forecast_index(
        [
            forecast("2026-01-02T00:00:00", "2026-01-01T11:30:00", 9500),
            forecast("2026-01-02T01:00:00", "2026-01-01T13:00:00", 9900),
        ]
    )
    from datetime import date, time, timedelta

    from app.service import CutoffPolicy

    policy = CutoffPolicy(cutoff_time=time(12, 0), day_offset=-1, timezone_name="Europe/London")

    def cutoff_for(start_time: datetime) -> datetime:
        delivery_date = start_time.astimezone(timezone.utc).date()
        local = datetime.combine(
            delivery_date + timedelta(days=policy.day_offset),
            policy.cutoff_time,
            tzinfo=timezone.utc,
        )
        return local

    outcomes = select_for_intervals(
        index,
        [ts("2026-01-02T00:00:00"), ts("2026-01-02T01:00:00")],
        cutoff_for,
    )
    assert outcomes[ts("2026-01-02T00:00:00")].selected.generation_mw == 9500
    # Published 13:00 on the day before -> after the 12:00 cutoff -> not eligible.
    assert outcomes[ts("2026-01-02T01:00:00")].selected is None
    assert date(2026, 1, 2).isoformat() == "2026-01-02"
