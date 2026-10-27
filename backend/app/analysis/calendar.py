"""Delivery-interval calendar helpers.

The delivery calendar is built from *business dates* in Europe/London and
converted to UTC instants.  Iterating local dates (rather than UTC days) keeps
the calendar correct across DST transitions, where a local day contains 23 or
25 hours.  January 2026 contains no transition, so every local day maps to a
plain 48-interval UTC day.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

INTERVAL_MINUTES = 30
INTERVALS_PER_DAY = 48
FORECAST_INTERVAL_MINUTES = 60  # WINDFOR publishes hourly values


def build_delivery_intervals(
    date_from: date,
    date_to: date,
    tz: ZoneInfo = ZoneInfo("Europe/London"),
) -> list[datetime]:
    """Return UTC start times for every half-hourly interval in the range.

    Each *local* day is expanded by walking UTC from local midnight to the
    next local midnight, so a DST day naturally yields 46 or 50 intervals
    instead of producing duplicated or non-existent wall-clock instants.
    """
    if date_from > date_to:
        return []
    intervals: list[datetime] = []
    day = date_from
    one_day = timedelta(days=1)
    step = timedelta(minutes=INTERVAL_MINUTES)
    while day <= date_to:
        day_start = datetime.combine(day, time(0, 0), tzinfo=tz).astimezone(timezone.utc)
        next_day = datetime.combine(day + one_day, time(0, 0), tzinfo=tz).astimezone(
            timezone.utc
        )
        cursor = day_start
        while cursor < next_day:
            intervals.append(cursor)
            cursor += step
        day += one_day
    return intervals


def expected_interval_count(date_from: date, date_to: date) -> int:
    if date_from > date_to:
        return 0
    return (date_to - date_from).days * INTERVALS_PER_DAY + INTERVALS_PER_DAY


def hour_floor(dt: datetime) -> datetime:
    """Return the start of the hour (UTC) containing ``dt``."""
    return dt.replace(minute=0, second=0, microsecond=0)


def business_date(dt: datetime, tz: ZoneInfo = ZoneInfo("Europe/London")) -> str:
    """ISO date of an instant in the business timezone."""
    return dt.astimezone(tz).date().isoformat()


def parse_iso_date(value: str) -> date:
    return date.fromisoformat(value)
