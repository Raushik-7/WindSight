"""Domain models shared by the ingestion, analysis and API layers.

All timestamps are timezone-aware.  ``start_time`` always refers to the
beginning of the delivery interval and ``publish_time`` always refers to the
moment the source record was published; the two are never conflated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Interval status values (kept as plain strings so they serialise cleanly)
# ---------------------------------------------------------------------------
STATUS_MATCHED = "matched"
STATUS_MISSING_FORECAST = "missing_eligible_forecast"
STATUS_MISSING_ACTUAL = "missing_actual"
STATUS_MISSING_BOTH = "missing_forecast_and_actual"

ALL_STATUSES = (
    STATUS_MATCHED,
    STATUS_MISSING_FORECAST,
    STATUS_MISSING_ACTUAL,
    STATUS_MISSING_BOTH,
)


@dataclass(frozen=True)
class ActualGeneration:
    """One half-hourly actual wind generation observation (FUELHH)."""

    start_time: datetime
    generation_mw: float
    publish_time: Optional[datetime] = None
    settlement_date: Optional[str] = None
    settlement_period: Optional[int] = None
    source: str = "FUELHH"


@dataclass(frozen=True)
class WindForecast:
    """One published wind generation forecast value (WINDFOR)."""

    start_time: datetime
    publish_time: datetime
    generation_mw: float
    source: str = "WINDFOR"


@dataclass(frozen=True)
class ExcludedRecord:
    """A source record dropped during normalisation, with the reason why."""

    dataset: str
    reason: str
    detail: str
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class MatchedObservation:
    """A single expected delivery interval joined with its selected forecast."""

    start_time: datetime
    delivery_date: str
    decision_cutoff: datetime
    status: str
    forecast_mw: Optional[float] = None
    actual_mw: Optional[float] = None
    selected_publish_time: Optional[datetime] = None
    # Hourly WINDFOR interval the forecast value was broadcast from.
    forecast_source_start: Optional[datetime] = None
    error_mw: Optional[float] = None
    absolute_error_mw: Optional[float] = None
    squared_error_mw2: Optional[float] = None
    exclusion_reason: Optional[str] = None

    @property
    def is_matched(self) -> bool:
        return self.status == STATUS_MATCHED


@dataclass
class MetricSet:
    """Accuracy metrics over a set of matched observations.

    When ``n == 0`` every metric is ``None`` (unavailable) - an empty dataset
    never yields a misleading zero.
    """

    n: int = 0
    mae: Optional[float] = None
    rmse: Optional[float] = None
    bias: Optional[float] = None
    mape: Optional[float] = None
    mape_n: int = 0
    mape_excluded_zero_actual: int = 0
    median_ae: Optional[float] = None
    p90_ae: Optional[float] = None
    max_ae: Optional[float] = None
    overforecast_n: int = 0
    underforecast_n: int = 0
    exact_n: int = 0

    @property
    def available(self) -> bool:
        return self.n > 0


@dataclass
class SourceData:
    """Raw-but-normalised upstream records plus their provenance."""

    actuals: list[ActualGeneration]
    forecasts: list[WindForecast]
    retrieved_at: Optional[datetime]
    origin: str  # "live" | "cache" | "snapshot" | "mixed"
    origin_detail: str
    exclusions: list[ExcludedRecord] = field(default_factory=list)
    fetch_errors: list[str] = field(default_factory=list)
    upstream_requests: int = 0
    # Optional store-specific detail (e.g. import runs, row counts).
    extra: dict = field(default_factory=dict)
