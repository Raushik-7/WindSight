"""Delivery-interval calendar: counts, timezone handling and DST."""

from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from app.analysis.calendar import (
    build_delivery_intervals,
    business_date,
    expected_interval_count,
    hour_floor,
)

LONDON = ZoneInfo("Europe/London")


def test_january_2026_has_1488_half_hourly_intervals():
    intervals = build_delivery_intervals(date(2026, 1, 1), date(2026, 1, 31), LONDON)
    assert len(intervals) == 1488
    assert expected_interval_count(date(2026, 1, 1), date(2026, 1, 31)) == 1488
    assert len(set(intervals)) == 1488
    assert intervals == sorted(intervals)


def test_intervals_are_utc_and_align_with_utc_midnight_in_january():
    intervals = build_delivery_intervals(date(2026, 1, 15), date(2026, 1, 15), LONDON)
    assert len(intervals) == 48
    assert all(i.tzinfo is not None for i in intervals)
    assert intervals[0] == datetime(2026, 1, 15, 0, 0, tzinfo=timezone.utc)
    assert intervals[1] == datetime(2026, 1, 15, 0, 30, tzinfo=timezone.utc)
    assert intervals[-1] == datetime(2026, 1, 15, 23, 30, tzinfo=timezone.utc)


def test_spring_forward_day_yields_46_intervals_without_duplicates():
    # 29 March 2026 is the UK DST start date (local day is 23 hours long).
    intervals = build_delivery_intervals(date(2026, 3, 29), date(2026, 3, 29), LONDON)
    assert len(intervals) == 46
    assert len(set(intervals)) == 46


def test_autumn_back_day_yields_50_intervals():
    intervals = build_delivery_intervals(date(2026, 10, 25), date(2026, 10, 25), LONDON)
    assert len(intervals) == 50
    assert len(set(intervals)) == 50


def test_business_date_uses_the_business_timezone():
    instant = datetime(2026, 1, 15, 23, 45, tzinfo=timezone.utc)
    assert business_date(instant, LONDON) == "2026-01-15"
    # 23:45 UTC on 14 Jan is still 14 Jan in London; in summer it would differ.
    summer = datetime(2026, 7, 14, 23, 45, tzinfo=timezone.utc)
    assert business_date(summer, LONDON) == "2026-07-15"


def test_hour_floor():
    assert hour_floor(datetime(2026, 1, 15, 10, 30, tzinfo=timezone.utc)) == datetime(
        2026, 1, 15, 10, 0, tzinfo=timezone.utc
    )


def test_empty_range_is_empty():
    assert build_delivery_intervals(date(2026, 1, 5), date(2026, 1, 1), LONDON) == []
    assert expected_interval_count(date(2026, 1, 5), date(2026, 1, 1)) == 0
