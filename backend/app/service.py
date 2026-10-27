"""Analysis service: turns source records into traceable analytical results.

The service owns the cutoff policy, memoises expensive recomputations and
returns everything the API needs to expose: observations, metrics, coverage,
daily/hourly breakdowns, data-quality counters and provenance.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from .analysis.calendar import (
    INTERVALS_PER_DAY,
    build_delivery_intervals,
    expected_interval_count,
    hour_floor,
)
from .analysis.matching import build_observations
from .analysis.metrics import compute_metrics, describe_bias
from .analysis.selection import build_forecast_index, select_for_intervals
from .config import Settings
from .models import (
    ALL_STATUSES,
    STATUS_MATCHED,
    MatchedObservation,
    MetricSet,
    SourceData,
)
from .store import DatabaseStore

ERROR_BUCKETS = [
    (-float("inf"), -5000.0),
    (-5000.0, -2000.0),
    (-2000.0, -500.0),
    (-500.0, 0.0),
    (0.0, 500.0),
    (500.0, 2000.0),
    (2000.0, 5000.0),
    (5000.0, float("inf")),
]


@dataclass(frozen=True)
class CutoffPolicy:
    cutoff_time: time
    day_offset: int
    timezone_name: str

    @property
    def label(self) -> str:
        offset = f"{self.day_offset:+d}d"
        return f"{self.cutoff_time.strftime('%H:%M')} {self.timezone_name} ({offset})"

    @property
    def description(self) -> str:
        if self.day_offset == -1:
            relation = "the calendar day before each delivery date"
        elif self.day_offset == 0:
            relation = "the delivery date itself"
        else:
            relation = f"{abs(self.day_offset)} calendar days before each delivery date"
        return (
            f"Day-ahead decision cutoff: {self.cutoff_time.strftime('%H:%M')} "
            f"{self.timezone_name} on {relation}. Only forecasts with "
            f"publishTime <= cutoff are eligible; the latest eligible publication "
            f"wins. This is a configurable analytical assumption, not a verified "
            f"market deadline."
        )

    @property
    def key(self) -> tuple[str, int, str]:
        return (self.cutoff_time.isoformat(), self.day_offset, self.timezone_name)


@dataclass
class AnalysisResult:
    date_from: date
    date_to: date
    cutoff: CutoffPolicy
    observations: list[MatchedObservation]
    metrics: MetricSet
    expected_intervals: int
    status_counts: dict[str, int]
    daily: list[dict[str, Any]] = field(default_factory=list)
    by_hour: list[dict[str, Any]] = field(default_factory=list)
    error_distribution: list[dict[str, Any]] = field(default_factory=list)
    hourly_series: list[dict[str, Any]] = field(default_factory=list)
    excluded_after_cutoff: int = 0
    selected_publish_times: list[str] = field(default_factory=list)

    @property
    def matched(self) -> int:
        return self.status_counts.get(STATUS_MATCHED, 0)

    @property
    def coverage_pct(self) -> Optional[float]:
        if not self.expected_intervals:
            return None
        return 100.0 * self.matched / self.expected_intervals


class AnalysisService:
    """Facade used by the API layer."""

    def __init__(self, settings: Settings, store: Optional[DatabaseStore] = None) -> None:
        self.settings = settings
        self.store = store or DatabaseStore(settings)
        self._lock = threading.Lock()
        self._results: dict[tuple, AnalysisResult] = {}

    # ------------------------------------------------------------------ #
    @property
    def tz(self) -> ZoneInfo:
        return self.settings.tz

    def default_cutoff(self) -> CutoffPolicy:
        return CutoffPolicy(
            cutoff_time=self.settings.cutoff_time,
            day_offset=self.settings.cutoff_day_offset,
            timezone_name=self.settings.business_timezone,
        )

    def resolve_cutoff(
        self,
        cutoff: Optional[str] = None,
        cutoff_offset_days: Optional[int] = None,
    ) -> CutoffPolicy:
        """Build a cutoff policy from request parameters (or the defaults)."""
        parsed_time = self.settings.cutoff_time
        if cutoff:
            try:
                hour_s, minute_s = cutoff.strip().split(":")
                hour, minute = int(hour_s), int(minute_s)
            except (ValueError, AttributeError) as exc:
                raise ValueError(
                    "cutoff must be formatted as HH:MM in 24-hour time"
                ) from exc
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError("cutoff must be a valid time of day (HH:MM)")
            parsed_time = time(hour, minute)
        offset = self.settings.cutoff_day_offset
        if cutoff_offset_days is not None:
            if cutoff_offset_days not in (-1, 0):
                raise ValueError("cutoff_offset_days must be -1 (day-ahead) or 0 (delivery day)")
            offset = cutoff_offset_days
        return CutoffPolicy(
            cutoff_time=parsed_time,
            day_offset=offset,
            timezone_name=self.settings.business_timezone,
        )

    def source_data(self, force_refresh: bool = False) -> SourceData:
        return self.store.load(force_refresh=force_refresh)

    # ------------------------------------------------------------------ #
    def analyze(
        self,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        cutoff: Optional[CutoffPolicy] = None,
    ) -> AnalysisResult:
        date_from = date_from or self.settings.eval_start
        date_to = date_to or self.settings.eval_end
        if date_from > date_to:
            raise ValueError("date_from must not be after date_to")
        policy = cutoff or self.default_cutoff()
        key = (date_from.isoformat(), date_to.isoformat(), policy.key)
        with self._lock:
            cached = self._results.get(key)
        if cached is not None:
            return cached

        source = self.source_data()
        tz = self.tz

        def cutoff_for(start_time: datetime) -> datetime:
            delivery_date = start_time.astimezone(tz).date()
            local = datetime.combine(
                delivery_date + timedelta(days=policy.day_offset),
                policy.cutoff_time,
                tzinfo=tz,
            )
            return local.astimezone(timezone.utc)

        intervals = build_delivery_intervals(date_from, date_to, tz)
        forecast_index = build_forecast_index(source.forecasts)
        actual_index = {a.start_time: a for a in source.actuals}
        # Select once per delivery interval *and* once per containing hour, so
        # an hourly WINDFOR value covers both half-hours it spans.
        selection_keys = sorted({*intervals, *(hour_floor(i) for i in intervals)})
        selections = select_for_intervals(forecast_index, selection_keys, cutoff_for)
        observations = build_observations(intervals, selections, actual_index, tz)

        status_counts = {status: 0 for status in ALL_STATUSES}
        for obs in observations:
            status_counts[obs.status] = status_counts.get(obs.status, 0) + 1

        metrics = compute_metrics(observations)
        result = AnalysisResult(
            date_from=date_from,
            date_to=date_to,
            cutoff=policy,
            observations=observations,
            metrics=metrics,
            expected_intervals=len(intervals),
            status_counts=status_counts,
            excluded_after_cutoff=sum(
                1
                for o in observations
                if o.exclusion_reason == "all_forecasts_published_after_cutoff"
            ),
            selected_publish_times=sorted(
                {
                    obs.selected_publish_time.isoformat()
                    for obs in observations
                    if obs.selected_publish_time is not None
                }
            ),
        )
        result.daily = self._daily_breakdown(observations, date_from, date_to)
        result.by_hour = self._hour_breakdown(observations)
        result.error_distribution = self._error_distribution(observations)
        result.hourly_series = self._hourly_series(observations)

        with self._lock:
            self._results[key] = result
        return result

    # ------------------------------------------------------------------ #
    @staticmethod
    def _daily_breakdown(
        observations: list[MatchedObservation], date_from: date, date_to: date
    ) -> list[dict[str, Any]]:
        grouped: dict[str, list[MatchedObservation]] = {}
        for obs in observations:
            grouped.setdefault(obs.delivery_date, []).append(obs)

        rows: list[dict[str, Any]] = []
        day = date_from
        while day <= date_to:
            key = day.isoformat()
            day_obs = grouped.get(key, [])
            matched = [o for o in day_obs if o.status == STATUS_MATCHED]
            metrics = compute_metrics(day_obs)
            rows.append(
                {
                    "date": key,
                    "expected": len(day_obs),
                    "matched": len(matched),
                    "coverage_pct": (
                        100.0 * len(matched) / len(day_obs) if day_obs else None
                    ),
                    "mae_mw": metrics.mae,
                    "rmse_mw": metrics.rmse,
                    "bias_mw": metrics.bias,
                    "mape_pct": metrics.mape,
                    "n": metrics.n,
                    "mean_forecast_mw": (
                        sum(o.forecast_mw for o in matched) / len(matched)
                        if matched
                        else None
                    ),
                    "mean_actual_mw": (
                        sum(o.actual_mw for o in matched) / len(matched)
                        if matched
                        else None
                    ),
                }
            )
            day += timedelta(days=1)
        return rows

    @staticmethod
    def _hour_breakdown(observations: list[MatchedObservation]) -> list[dict[str, Any]]:
        grouped: dict[int, list[MatchedObservation]] = {h: [] for h in range(24)}
        for obs in observations:
            if obs.status != STATUS_MATCHED:
                continue
            grouped[obs.start_time.hour].append(obs)
        rows = []
        for hour in range(24):
            metrics = compute_metrics(grouped[hour])
            rows.append(
                {
                    "hour_utc": hour,
                    "n": metrics.n,
                    "mae_mw": metrics.mae,
                    "bias_mw": metrics.bias,
                    "mean_actual_mw": (
                        sum(o.actual_mw for o in grouped[hour]) / len(grouped[hour])
                        if grouped[hour]
                        else None
                    ),
                }
            )
        return rows

    @staticmethod
    def _error_distribution(observations: list[MatchedObservation]) -> list[dict[str, Any]]:
        counts = [0] * (len(ERROR_BUCKETS) - 1)
        for obs in observations:
            if obs.status != STATUS_MATCHED or obs.error_mw is None:
                continue
            for idx in range(len(ERROR_BUCKETS) - 1):
                low, high = ERROR_BUCKETS[idx]
                if low < obs.error_mw <= high or (
                    idx == 0 and obs.error_mw == low
                ):
                    counts[idx] += 1
                    break
        labels = []
        for idx in range(len(ERROR_BUCKETS) - 1):
            low, high = ERROR_BUCKETS[idx]
            low_label = "-inf" if low == -float("inf") else f"{low:,.0f}"
            high_label = "inf" if high == float("inf") else f"{high:,.0f}"
            labels.append(
                {
                    "range": f"{low_label} to {high_label} MW",
                    "count": counts[idx],
                    "direction": (
                        "under" if high <= 0 else ("over" if low >= 0 else "mixed")
                    ),
                }
            )
        return labels

    @staticmethod
    def _hourly_series(observations: list[MatchedObservation]) -> list[dict[str, Any]]:
        """Hourly forecast/actual pairs for charting (744 points for January)."""
        grouped: dict[datetime, list[MatchedObservation]] = {}
        for obs in observations:
            if obs.status != STATUS_MATCHED:
                continue
            grouped.setdefault(hour_floor(obs.start_time), []).append(obs)
        series = []
        for start in sorted(grouped):
            rows = grouped[start]
            series.append(
                {
                    "time": start.isoformat(),
                    "forecast_mw": sum(r.forecast_mw for r in rows) / len(rows),
                    "actual_mw": sum(r.actual_mw for r in rows) / len(rows),
                }
            )
        return series

    # ------------------------------------------------------------------ #
    def overview(self, cutoff: Optional[CutoffPolicy] = None) -> dict[str, Any]:
        policy = cutoff or self.default_cutoff()
        result = self.analyze(
            self.settings.eval_start, self.settings.eval_end, policy
        )
        source = self.source_data()
        metrics = result.metrics
        matched = result.matched

        if metrics.available:
            direction = (
                "overestimate" if (metrics.bias or 0) > 0 else "underestimate"
            )
            summary = (
                f"Between {self.settings.eval_start:%d %B %Y} and "
                f"{self.settings.eval_end:%d %B %Y}, {matched:,} of "
                f"{result.expected_intervals:,} expected half-hourly delivery "
                f"intervals had both an eligible forecast and actual outturn. "
                f"Mean absolute error was {metrics.mae:,.1f} MW, RMSE "
                f"{metrics.rmse:,.1f} MW and mean bias {metrics.bias:+,.1f} MW, "
                f"so on average the selected forecasts {direction} actual wind "
                f"generation. MAPE was {metrics.mape:.1f}% over "
                f"{metrics.mape_n:,} intervals with non-zero actual output."
                if metrics.mape is not None
                else f"Between {self.settings.eval_start:%d %B %Y} and "
                f"{self.settings.eval_end:%d %B %Y}, {matched:,} of "
                f"{result.expected_intervals:,} intervals matched; MAE "
                f"{metrics.mae:,.1f} MW, bias {metrics.bias:+,.1f} MW. MAPE is "
                f"unavailable because every actual value in the sample is zero."
            )
        else:
            summary = (
                "No matched forecast/actual intervals are available for this "
                "selection, so accuracy metrics are reported as unavailable "
                "rather than zero. Check the data-quality panel for the reason."
            )

        return {
            "period": {
                "start": self.settings.eval_start.isoformat(),
                "end": self.settings.eval_end.isoformat(),
                "label": f"{self.settings.eval_start:%d %B} – {self.settings.eval_end:%d %B %Y}",
                "expected_intervals": result.expected_intervals,
                "intervals_per_day": INTERVALS_PER_DAY,
            },
            "cutoff": _cutoff_payload(policy),
            "metrics": _metrics_payload(metrics),
            "coverage": {
                "expected": result.expected_intervals,
                "matched": matched,
                "coverage_pct": result.coverage_pct,
                "status_counts": result.status_counts,
            },
            "summary": summary,
            "bias_narrative": describe_bias(metrics.bias, metrics.mae),
            "daily": result.daily,
            "series": result.hourly_series,
            "provenance": self.provenance(),
            "warnings": self.warnings(),
        }

    # ------------------------------------------------------------------ #
    def provenance(self) -> dict[str, Any]:
        try:
            source = self.source_data()
        except Exception as exc:  # surfaced as a warning, never as fake data
            return {"available": False, "error": str(exc)}
        return {
            "available": True,
            "origin": source.origin,
            "origin_detail": source.origin_detail,
            "retrieved_at": (
                source.retrieved_at.isoformat() if source.retrieved_at else None
            ),
            "upstream_requests": source.upstream_requests,
            "actual_records": len(source.actuals),
            "forecast_records": len(source.forecasts),
            "excluded_records": len(source.exclusions),
            "fetch_errors": source.fetch_errors,
            "database_kind": source.extra.get("database_kind"),
            "database_url": source.extra.get("database_url"),
            "last_import": _run_summary(source.extra.get("runs")),
            "source_datasets": [
                {
                    "name": "FUELHH",
                    "role": "Actual half-hourly wind generation outturn",
                    "docs": "https://bmrs.elexon.co.uk/api-documentation/endpoint/datasets/FUELHH/stream",
                },
                {
                    "name": "WINDFOR",
                    "role": "Published wind generation forecast (hourly)",
                    "docs": "https://bmrs.elexon.co.uk/api-documentation/endpoint/datasets/WINDFOR/stream",
                },
            ],
            "base_url": self.settings.elexon_base_url,
        }

    def warnings(self) -> list[dict[str, str]]:
        warnings: list[dict[str, str]] = []
        try:
            source = self.source_data()
        except Exception as exc:
            warnings.append(
                {"level": "error", "message": f"Source data unavailable: {exc}"}
            )
            return warnings
        runs = list(source.extra.get("runs") or [])
        if runs:
            latest = runs[0]
            if latest.status != "completed":
                warnings.append(
                    {
                        "level": "warning",
                        "message": (
                            f"Latest import run #{latest.id} ({latest.dataset}, "
                            f"{latest.source}) finished as '{latest.status}'. "
                            f"{latest.coverage_detail or ''} {latest.error_detail or ''}"
                        ).strip(),
                    }
                )
            if latest.source == "snapshot":
                warnings.append(
                    {
                        "level": "info",
                        "message": (
                            "Durable storage was seeded from the committed Elexon "
                            "snapshot (real records fetched on 2026-10-26). Run the "
                            "historical import CLI to refresh from the live API."
                        ),
                    }
                )
        for err in source.fetch_errors:
            warnings.append({"level": "warning", "message": err})
        if source.exclusions:
            warnings.append(
                {
                    "level": "info",
                    "message": (
                        f"{len(source.exclusions)} source records were excluded "
                        "during normalisation (see data quality)."
                    ),
                }
            )
        return warnings

    def data_quality(self, cutoff: Optional[CutoffPolicy] = None) -> dict[str, Any]:
        policy = cutoff or self.default_cutoff()
        result = self.analyze(
            self.settings.eval_start, self.settings.eval_end, policy
        )
        source = self.source_data()

        by_reason: dict[str, int] = {}
        for record in source.exclusions:
            by_reason[record.reason] = by_reason.get(record.reason, 0) + 1

        missed_reasons: dict[str, int] = {}
        for obs in result.observations:
            if obs.status == STATUS_MATCHED:
                continue
            key = obs.exclusion_reason or obs.status
            missed_reasons[key] = missed_reasons.get(key, 0) + 1

        return {
            "coverage": {
                "expected": result.expected_intervals,
                "matched": result.matched,
                "coverage_pct": result.coverage_pct,
                "status_counts": result.status_counts,
            },
            "record_exclusions": by_reason,
            "excluded_examples": [
                {"dataset": r.dataset, "reason": r.reason, "detail": r.detail}
                for r in source.exclusions[:20]
            ],
            "interval_reasons": missed_reasons,
            "late_forecast_excluded_intervals": result.excluded_after_cutoff,
            "distinct_selected_publish_times": len(result.selected_publish_times),
            "selected_publish_times": result.selected_publish_times,
            "cutoff": _cutoff_payload(policy),
            "provenance": self.provenance(),
            "warnings": self.warnings(),
        }

    def refresh(self, source: str = "elexon_live") -> dict[str, Any]:
        """Controlled refresh: re-import durable history, then recompute."""
        results = self.store.run_import(source=source)
        with self._lock:
            self._results.clear()
        data = self.store.load(force_refresh=True)
        return {
            "imports": results,
            "origin": data.origin,
            "retrieved_at": data.retrieved_at.isoformat() if data.retrieved_at else None,
            "actual_records": len(data.actuals),
            "forecast_records": len(data.forecasts),
        }


# --------------------------------------------------------------------------- #
def _run_summary(runs: Any) -> Optional[dict[str, Any]]:
    """Compact description of the most recent import run."""
    if not runs:
        return None
    run = runs[0]
    return {
        "id": getattr(run, "id", None),
        "dataset": getattr(run, "dataset", None),
        "source": getattr(run, "source", None),
        "status": getattr(run, "status", None),
        "started_at": _iso(getattr(run, "started_at", None)),
        "finished_at": _iso(getattr(run, "finished_at", None)),
        "records_inserted": getattr(run, "records_inserted", 0),
        "records_updated": getattr(run, "records_updated", 0),
        "coverage_verified": getattr(run, "coverage_verified", False),
        "coverage_detail": getattr(run, "coverage_detail", None),
    }


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _cutoff_payload(policy: CutoffPolicy) -> dict[str, Any]:
    return {
        "time": policy.cutoff_time.strftime("%H:%M"),
        "day_offset": policy.day_offset,
        "timezone": policy.timezone_name,
        "label": policy.label,
        "description": policy.description,
    }


def _metrics_payload(metrics: MetricSet) -> dict[str, Any]:
    return {
        "available": metrics.available,
        "n": metrics.n,
        "mae_mw": metrics.mae,
        "rmse_mw": metrics.rmse,
        "bias_mw": metrics.bias,
        "mape_pct": metrics.mape,
        "mape_n": metrics.mape_n,
        "mape_excluded_zero_actual": metrics.mape_excluded_zero_actual,
        "median_ae_mw": metrics.median_ae,
        "p90_ae_mw": metrics.p90_ae,
        "max_ae_mw": metrics.max_ae,
        "overforecast_n": metrics.overforecast_n,
        "underforecast_n": metrics.underforecast_n,
        "exact_n": metrics.exact_n,
    }
