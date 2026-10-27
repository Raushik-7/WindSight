"""Pydantic response schemas for the WindSight API."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class ErrorBody(BaseModel):
    code: str = Field(examples=["invalid_parameter"])
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody


class CutoffPayload(BaseModel):
    time: str = Field(examples=["12:00"])
    day_offset: int = Field(description="-1 = day before delivery date, 0 = delivery date")
    timezone: str
    label: str
    description: str


class MetricPayload(BaseModel):
    available: bool = Field(description="False when the sample is empty; metrics are then null")
    n: int = Field(description="Matched observations used for MAE/RMSE/bias")
    mae_mw: Optional[float] = None
    rmse_mw: Optional[float] = None
    bias_mw: Optional[float] = Field(default=None, description="Positive = overforecast")
    mape_pct: Optional[float] = None
    mape_n: int = Field(description="Observations used for MAPE (non-zero actuals)")
    mape_excluded_zero_actual: int
    median_ae_mw: Optional[float] = None
    p90_ae_mw: Optional[float] = None
    max_ae_mw: Optional[float] = None
    overforecast_n: int
    underforecast_n: int
    exact_n: int


class CoveragePayload(BaseModel):
    expected: int
    matched: int
    coverage_pct: Optional[float]
    status_counts: dict[str, int]


class PeriodPayload(BaseModel):
    start: str
    end: str
    label: str
    expected_intervals: int
    intervals_per_day: int


class DatasetPayload(BaseModel):
    name: str
    role: str
    docs: str


class ProvenancePayload(BaseModel):
    available: bool
    origin: Optional[str] = Field(
        default=None, description="live | cache | snapshot | mixed"
    )
    origin_detail: Optional[str] = None
    retrieved_at: Optional[str] = None
    upstream_requests: Optional[int] = None
    actual_records: Optional[int] = None
    forecast_records: Optional[int] = None
    excluded_records: Optional[int] = None
    fetch_errors: Optional[list[str]] = None
    source_datasets: Optional[list[DatasetPayload]] = None
    base_url: Optional[str] = None
    database_kind: Optional[str] = Field(default=None, description="sqlite | postgresql")
    database_url: Optional[str] = Field(default=None, description="Credentials redacted")
    last_import: Optional[dict[str, Any]] = None
    error: Optional[str] = None


class WarningPayload(BaseModel):
    level: str = Field(examples=["warning"])
    message: str


class OverviewResponse(BaseModel):
    period: PeriodPayload
    cutoff: CutoffPayload
    metrics: MetricPayload
    coverage: CoveragePayload
    summary: str
    bias_narrative: str
    daily: list[dict[str, Any]]
    series: list[dict[str, Any]]
    provenance: ProvenancePayload
    warnings: list[WarningPayload]


class IntervalRow(BaseModel):
    start_utc: str
    start_local: str
    delivery_date: str
    slot: int = Field(description="0-47 position within the delivery day")
    status: str
    forecast_mw: Optional[float] = None
    actual_mw: Optional[float] = None
    publish_time: Optional[str] = None
    forecast_source_start: Optional[str] = None
    decision_cutoff: str
    error_mw: Optional[float] = None
    absolute_error_mw: Optional[float] = None
    squared_error_mw2: Optional[float] = None
    exclusion_reason: Optional[str] = None
    is_extreme_error: bool = False


class ForecastsResponse(BaseModel):
    date: str
    cutoff: CutoffPayload
    intervals: list[IntervalRow]
    metrics: MetricPayload
    coverage: CoveragePayload
    selected_publish_times: list[str]
    provenance: ProvenancePayload
    warnings: list[WarningPayload]
    notes: list[str]


class AccuracyResponse(BaseModel):
    date_from: str
    date_to: str
    cutoff: CutoffPayload
    metrics: MetricPayload
    coverage: CoveragePayload
    daily: list[dict[str, Any]]
    by_hour: list[dict[str, Any]]
    error_distribution: list[dict[str, Any]]
    provenance: ProvenancePayload
    warnings: list[WarningPayload]


class DataQualityResponse(BaseModel):
    coverage: CoveragePayload
    record_exclusions: dict[str, int]
    excluded_examples: list[dict[str, Any]]
    interval_reasons: dict[str, int]
    late_forecast_excluded_intervals: int
    distinct_selected_publish_times: int
    selected_publish_times: list[str]
    cutoff: CutoffPayload
    provenance: ProvenancePayload
    warnings: list[WarningPayload]
    import_runs: list[dict[str, Any]] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str
    data: dict[str, Any]
    cutoff: CutoffPayload
    version: str = "1.0.0"


class RefreshResponse(BaseModel):
    """Result of a protected operator refresh."""

    imports: list[dict[str, Any]]
    origin: str
    retrieved_at: Optional[str]
    actual_records: int
    forecast_records: int
