"""Join selected forecasts with actual outturn on the delivery interval.

Forecast/actual matching is performed on ``startTime`` (the delivery
interval).  ``publishTime`` is never used as a join key.

Resolution note: WINDFOR publishes **hourly** values while FUELHH publishes
**half-hourly** outturn.  The hourly forecast value is applied to each of the
two half-hourly intervals it spans (a constant-MW disaggregation, which is
energy conserving: the mean of the two half-hourly errors equals the hourly
error).  The source hourly interval is carried on every observation so the
provenance stays visible.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

from ..models import (
    STATUS_MATCHED,
    STATUS_MISSING_ACTUAL,
    STATUS_MISSING_BOTH,
    STATUS_MISSING_FORECAST,
    ActualGeneration,
    MatchedObservation,
)
from .calendar import hour_floor
from .selection import SelectionOutcome


def build_observations(
    intervals: Iterable[datetime],
    selections: dict[datetime, SelectionOutcome],
    actuals: dict[datetime, ActualGeneration],
    tz: ZoneInfo = ZoneInfo("Europe/London"),
) -> list[MatchedObservation]:
    observations: list[MatchedObservation] = []
    for start_time in intervals:
        # WINDFOR is hourly: when the half-hour itself carries no selection,
        # fall back to the containing hour that the forecast actually spans.
        outcome = selections.get(start_time)
        hourly_outcome = selections.get(hour_floor(start_time))
        if outcome is None:
            outcome = hourly_outcome
        elif outcome.selected is None and hourly_outcome is not None:
            outcome = hourly_outcome
        cutoff = (
            outcome.decision_cutoff
            if outcome is not None
            else datetime.min.replace(tzinfo=timezone.utc)
        )
        actual = actuals.get(start_time)
        selected = outcome.selected if outcome is not None else None

        forecast_mw = selected.generation_mw if selected else None
        actual_mw = actual.generation_mw if actual else None
        publish_time = selected.publish_time if selected else None

        if forecast_mw is None and actual_mw is None:
            status = STATUS_MISSING_BOTH
            reason = "no_eligible_forecast_and_no_actual"
        elif forecast_mw is None:
            status = STATUS_MISSING_FORECAST
            reason = outcome.excluded_reason if outcome else "no_selection"
        elif actual_mw is None:
            status = STATUS_MISSING_ACTUAL
            reason = "actual_generation_unavailable_for_interval"
        else:
            status = STATUS_MATCHED
            reason = None

        error: Optional[float] = None
        absolute: Optional[float] = None
        squared: Optional[float] = None
        if status == STATUS_MATCHED:
            error = forecast_mw - actual_mw
            absolute = abs(error)
            squared = error * error

        observations.append(
            MatchedObservation(
                start_time=start_time,
                delivery_date=start_time.astimezone(tz).date().isoformat(),
                decision_cutoff=cutoff,
                status=status,
                forecast_mw=forecast_mw,
                actual_mw=actual_mw,
                selected_publish_time=publish_time,
                forecast_source_start=selected.start_time if selected else None,
                error_mw=error,
                absolute_error_mw=absolute,
                squared_error_mw2=squared,
                exclusion_reason=reason,
            )
        )
    return observations
