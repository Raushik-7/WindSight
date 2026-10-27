"""Decision-cutoff aware forecast selection.

The single most important rule in this product:

    for a delivery interval, take every forecast published for that interval,
    drop anything published *after* the decision cutoff, and keep the record
    with the latest publication time among what remains.

A later forecast is never preferred just because it scores better against the
actual value - that would leak the answer into the evaluation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterable, Optional

from ..models import WindForecast


@dataclass
class SelectionOutcome:
    """The result of applying the cutoff rule to one delivery interval."""

    start_time: datetime
    decision_cutoff: datetime
    selected: Optional[WindForecast]
    eligible_count: int = 0
    excluded_after_cutoff: int = 0
    # The most recent candidate regardless of cutoff, for explaining misses.
    latest_candidate: Optional[WindForecast] = None

    @property
    def excluded_reason(self) -> Optional[str]:
        if self.selected is not None:
            return None
        if self.latest_candidate is None:
            return "no_forecast_published_for_interval"
        return "all_forecasts_published_after_cutoff"


def build_forecast_index(
    forecasts: Iterable[WindForecast],
) -> dict[datetime, list[WindForecast]]:
    """Group forecasts by the delivery interval they describe."""
    index: dict[datetime, list[WindForecast]] = {}
    for forecast in forecasts:
        index.setdefault(forecast.start_time, []).append(forecast)
    for records in index.values():
        records.sort(key=lambda r: (r.publish_time, r.generation_mw))
    return index


def select_latest_eligible(
    candidates: Iterable[WindForecast],
    decision_cutoff: datetime,
    start_time: datetime,
) -> SelectionOutcome:
    """Apply the eligibility rule and pick the latest eligible publication.

    Tie-break: records sharing the same ``publishTime`` are resolved
    deterministically by the greater ``generation`` value (records are sorted
    ascending, so the last one wins) - identical inputs always produce an
    identical selection.
    """
    if decision_cutoff.tzinfo is None:  # pragma: no cover - defensive
        raise ValueError("decision cutoff must be timezone-aware")

    ordered = sorted(candidates, key=lambda r: (r.publish_time, r.generation_mw))
    eligible = [r for r in ordered if r.publish_time <= decision_cutoff]
    excluded = len(ordered) - len(eligible)
    latest = ordered[-1] if ordered else None
    selected = eligible[-1] if eligible else None
    return SelectionOutcome(
        start_time=start_time,
        decision_cutoff=decision_cutoff,
        selected=selected,
        eligible_count=len(eligible),
        excluded_after_cutoff=excluded,
        latest_candidate=latest,
    )


def select_for_intervals(
    index: dict[datetime, list[WindForecast]],
    intervals: Iterable[datetime],
    cutoff_for: Callable[[datetime], datetime],
) -> dict[datetime, SelectionOutcome]:
    """Select a forecast for every delivery interval in ``intervals``."""
    outcomes: dict[datetime, SelectionOutcome] = {}
    for start_time in intervals:
        cutoff = cutoff_for(start_time)
        outcomes[start_time] = select_latest_eligible(
            index.get(start_time, ()), cutoff, start_time
        )
    return outcomes


def is_eligible(publish_time: datetime, decision_cutoff: datetime) -> bool:
    if publish_time.tzinfo is None:
        raise ValueError("publish time must be timezone-aware")
    return publish_time <= decision_cutoff


def ensure_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt
