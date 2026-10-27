"""HTTP routes for the WindSight application API.

Business logic lives in :mod:`app.service`; these handlers only validate
input, call the service and shape the response.  Errors are returned as a
stable ``{"error": {"code", "message"}}`` body with an appropriate status.
"""

from __future__ import annotations

import secrets
from datetime import date, datetime, timezone
from typing import Optional as _Optional
from typing import Any, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse, Response

from ..config import Settings
from ..export import export_filename, observations_to_csv
from ..service import AnalysisResult, AnalysisService, CutoffPolicy
from ..source import DataUnavailableError
from . import schemas

router = APIRouter(prefix="/api")


def get_service(request: Request) -> AnalysisService:
    return request.app.state.service


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


def _resolve(
    service: AnalysisService,
    date_from: Optional[date],
    date_to: Optional[date],
    cutoff: Optional[str],
    cutoff_offset_days: Optional[int],
) -> tuple[date, date, CutoffPolicy]:
    settings = service.settings
    start = date_from or settings.eval_start
    end = date_to or settings.eval_end
    if start > end:
        raise ValueError("'from' must not be after 'to'")
    if start < settings.eval_start or end > settings.eval_end:
        raise ValueError(
            f"Requested range must fall inside the evaluation period "
            f"{settings.eval_start.isoformat()} to {settings.eval_end.isoformat()}"
        )
    policy = service.resolve_cutoff(cutoff, cutoff_offset_days)
    return start, end, policy


def _run(service: AnalysisService, *args: Any, **kwargs: Any) -> AnalysisResult:
    try:
        return service.analyze(*args, **kwargs)
    except DataUnavailableError as exc:
        raise _unavailable(exc) from exc


def _unavailable(exc: Exception) -> JSONResponse:
    return error_response(
        503,
        "source_unavailable",
        "Live Elexon data and any local cache/snapshot are unavailable. "
        f"Details: {exc}",
    )


# --------------------------------------------------------------------------- #
@router.get("/health", response_model=schemas.HealthResponse)
def health(request: Request, service: AnalysisService = Depends(get_service)) -> Any:
    """Liveness + data readiness probe (never exposes credentials)."""
    store = request.app.state.store
    startup = getattr(request.app.state, "startup", {})
    database = store.health()
    try:
        source = service.source_data()
        data: dict[str, Any] = {
            "status": "ready",
            "origin": source.origin,
            "origin_detail": source.origin_detail,
            "retrieved_at": (
                source.retrieved_at.isoformat() if source.retrieved_at else None
            ),
            "actual_records": len(source.actuals),
            "forecast_records": len(source.forecasts),
            "fetch_errors": source.fetch_errors,
            "last_import": source.extra.get("last_import_run"),
        }
    except DataUnavailableError as exc:
        data = {"status": "unavailable", "detail": str(exc)}
    except Exception as exc:  # pragma: no cover - defensive
        data = {"status": "error", "detail": str(exc)}

    data["database"] = database
    data["startup"] = startup
    if database.get("reachable") is False:
        data["status"] = "degraded"

    payload = {
        "status": data.get("status", "unknown"),
        "data": data,
        "cutoff": _cutoff_dict(service.default_cutoff()),
    }
    model = schemas.HealthResponse(**payload)
    status_code = 200 if model.status in {"ready", "degraded"} else 503
    return JSONResponse(status_code=status_code, content=model.model_dump())


@router.get("/overview", response_model=schemas.OverviewResponse)
def overview(
    cutoff: Optional[str] = Query(None, description="Decision cutoff time, HH:MM (Europe/London)"),
    cutoff_offset_days: Optional[int] = Query(
        None, description="-1 = day before delivery (default), 0 = delivery day"
    ),
    service: AnalysisService = Depends(get_service),
) -> Any:
    try:
        policy = service.resolve_cutoff(cutoff, cutoff_offset_days)
        payload = service.overview(policy)
        return schemas.OverviewResponse(**payload)
    except ValueError as exc:
        return error_response(400, "invalid_parameter", str(exc))
    except DataUnavailableError as exc:
        return _unavailable(exc)


@router.get("/forecasts", response_model=schemas.ForecastsResponse)
def forecasts(
    date: date = Query(..., description="Delivery date (yyyy-mm-dd)"),
    cutoff: Optional[str] = Query(None, description="Decision cutoff time, HH:MM"),
    cutoff_offset_days: Optional[int] = Query(None, description="-1 or 0"),
    service: AnalysisService = Depends(get_service),
) -> Any:
    try:
        policy = service.resolve_cutoff(cutoff, cutoff_offset_days)
        settings = service.settings
        if date < settings.eval_start or date > settings.eval_end:
            raise ValueError(
                f"date must fall inside the evaluation period "
                f"{settings.eval_start.isoformat()} to {settings.eval_end.isoformat()}"
            )
        result = service.analyze(date, date, policy)
        rows = _interval_rows(result)
        publish_times = result.selected_publish_times
        return schemas.ForecastsResponse(
            date=date.isoformat(),
            cutoff=_cutoff_dict(policy),
            intervals=rows,
            metrics=_metrics_dict(result.metrics),
            coverage=_coverage_dict(result),
            selected_publish_times=publish_times,
            provenance=service.provenance(),
            warnings=service.warnings(),
            notes=_forecast_notes(result),
        )
    except ValueError as exc:
        return error_response(400, "invalid_parameter", str(exc))
    except DataUnavailableError as exc:
        return _unavailable(exc)


@router.get("/accuracy", response_model=schemas.AccuracyResponse)
def accuracy(
    date_from: Optional[date] = Query(None, alias="from"),
    date_to: Optional[date] = Query(None, alias="to"),
    cutoff: Optional[str] = Query(None),
    cutoff_offset_days: Optional[int] = Query(None),
    service: AnalysisService = Depends(get_service),
) -> Any:
    try:
        start, end, policy = _resolve(service, date_from, date_to, cutoff, cutoff_offset_days)
        result = service.analyze(start, end, policy)
        return schemas.AccuracyResponse(
            date_from=start.isoformat(),
            date_to=end.isoformat(),
            cutoff=_cutoff_dict(policy),
            metrics=_metrics_dict(result.metrics),
            coverage=_coverage_dict(result),
            daily=result.daily,
            by_hour=result.by_hour,
            error_distribution=result.error_distribution,
            provenance=service.provenance(),
            warnings=service.warnings(),
        )
    except ValueError as exc:
        return error_response(400, "invalid_parameter", str(exc))
    except DataUnavailableError as exc:
        return _unavailable(exc)


@router.get("/accuracy/daily")
def accuracy_daily(
    date_from: Optional[date] = Query(None, alias="from"),
    date_to: Optional[date] = Query(None, alias="to"),
    cutoff: Optional[str] = Query(None),
    cutoff_offset_days: Optional[int] = Query(None),
    service: AnalysisService = Depends(get_service),
) -> Any:
    try:
        start, end, policy = _resolve(service, date_from, date_to, cutoff, cutoff_offset_days)
        result = service.analyze(start, end, policy)
        return {
            "date_from": start.isoformat(),
            "date_to": end.isoformat(),
            "cutoff": _cutoff_dict(policy),
            "daily": result.daily,
        }
    except ValueError as exc:
        return error_response(400, "invalid_parameter", str(exc))
    except DataUnavailableError as exc:
        return _unavailable(exc)


@router.get("/data-quality", response_model=schemas.DataQualityResponse)
def data_quality(
    request: Request,
    cutoff: Optional[str] = Query(None),
    cutoff_offset_days: Optional[int] = Query(None),
    service: AnalysisService = Depends(get_service),
) -> Any:
    try:
        policy = service.resolve_cutoff(cutoff, cutoff_offset_days)
        payload = dict(service.data_quality(policy))
        payload["import_runs"] = request.app.state.store.import_runs(limit=10)
        return schemas.DataQualityResponse(**payload)
    except ValueError as exc:
        return error_response(400, "invalid_parameter", str(exc))
    except DataUnavailableError as exc:
        return _unavailable(exc)


@router.get("/methodology")
def methodology(
    service: AnalysisService = Depends(get_service),
    settings: Settings = Depends(get_settings),
) -> Any:
    policy = service.default_cutoff()
    return {
        "cutoff": _cutoff_dict(policy),
        "timezone": {
            "business": settings.business_timezone,
            "canonical": "UTC",
            "note": (
                "Timestamps are stored and compared in UTC; delivery dates and "
                "the decision cutoff are expressed in Europe/London. January 2026 "
                "has no DST transition, so local time equals UTC for the whole "
                "evaluation period."
            ),
        },
        "definitions": [
            {
                "term": "startTime",
                "meaning": "Start of the delivery interval the value describes.",
            },
            {
                "term": "publishTime",
                "meaning": "Moment the source record was published. Never used as a join key.",
            },
            {
                "term": "decision cutoff",
                "meaning": "Latest publication time still available when the historical procurement decision had to be made.",
            },
        ],
        "selection_rule": (
            "For each delivery interval: drop every forecast with publishTime > cutoff, "
            "then keep the record with the latest publishTime among those remaining. "
            "Ties on publishTime are broken deterministically by the greater generation "
            "value. A later forecast is never chosen because it scores better."
        ),
        "matching_rule": (
            "Forecasts and actuals are joined on the delivery interval (startTime). "
            "WINDFOR publishes hourly values and FUELHH publishes half-hourly outturn, "
            "so the hourly forecast value is applied to each of the two half-hourly "
            "intervals it spans; this is energy conserving, because the mean of the two "
            "half-hourly errors equals the hourly error."
        ),
        "error_convention": (
            "error_mw = forecast_mw - actual_mw. Positive = forecast overestimated "
            "wind generation; negative = forecast underestimated it."
        ),
        "metrics": {
            "mae": "mean(|forecast - actual|) in MW",
            "rmse": "sqrt(mean((forecast - actual)^2)) in MW",
            "bias": "mean(forecast - actual) in MW; positive = overforecast",
            "mape": "mean(|forecast - actual| / |actual|) * 100, computed only where actual != 0",
        },
        "mape_limitation": (
            "MAPE is undefined where actual generation is zero and unstable where it is "
            "close to zero. Those intervals are excluded and counted separately; MAPE "
            "is never presented as the sole quality measure."
        ),
        "missing_data": (
            "Missing values are never replaced with zero. Intervals without an eligible "
            "forecast or without actual outturn stay in the coverage report with an "
            "explicit status and are excluded from metrics that need both values."
        ),
        "datasets": [
            {
                "name": "FUELHH",
                "role": "Actual half-hourly generation outturn by fuel type, filtered to WIND",
                "docs": "https://bmrs.elexon.co.uk/api-documentation/endpoint/datasets/FUELHH/stream",
            },
            {
                "name": "WINDFOR",
                "role": "Published wind generation forecast (hourly), with publishTime per record",
                "docs": "https://bmrs.elexon.co.uk/api-documentation/endpoint/datasets/WINDFOR/stream",
            },
        ],
        "assumptions": [
            "The 12:00 Europe/London day-ahead cutoff is an analytical assumption pending client confirmation; it is configurable at runtime.",
            "WINDFOR startTime denotes the beginning of the forecast hour (matching the FUELHH convention).",
            "Forecast values are hourly averages in MW and are broadcast to the half-hourly intervals they span.",
        ],
    }


@router.get("/export")
def export_csv(
    date_from: Optional[date] = Query(None, alias="from"),
    date_to: Optional[date] = Query(None, alias="to"),
    cutoff: Optional[str] = Query(None),
    cutoff_offset_days: Optional[int] = Query(None),
    service: AnalysisService = Depends(get_service),
) -> Any:
    try:
        start, end, policy = _resolve(service, date_from, date_to, cutoff, cutoff_offset_days)
        result = service.analyze(start, end, policy)
        content = observations_to_csv(result.observations)
        filename = export_filename(start.isoformat(), end.isoformat())
        return Response(
            content=content,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except ValueError as exc:
        return error_response(400, "invalid_parameter", str(exc))
    except DataUnavailableError as exc:
        return _unavailable(exc)


@router.post("/refresh", response_model=schemas.RefreshResponse)
def refresh(
    request: Request,
    source: str = Query("elexon_live", pattern="^(elexon_live|snapshot)$"),
    x_admin_token: _Optional[str] = Header(default=None),
    service: AnalysisService = Depends(get_service),
) -> Any:
    """Controlled operator refresh: re-import durable history from Elexon.

    Protected because the public demo has no user authentication: the endpoint
    is disabled unless ``ADMIN_TOKEN`` is configured, and then requires the same
    value in the ``X-Admin-Token`` header.
    """
    settings = request.app.state.settings
    if not settings.admin_token:
        return error_response(
            403,
            "refresh_disabled",
            "Data refresh is disabled because ADMIN_TOKEN is not configured.",
        )
    if not x_admin_token or not secrets.compare_digest(x_admin_token, settings.admin_token):
        return error_response(401, "unauthorized", "A valid X-Admin-Token header is required.")

    try:
        payload = service.refresh(source=source)
        return schemas.RefreshResponse(**payload)
    except RuntimeError as exc:
        return error_response(409, "import_conflict", str(exc))
    except DataUnavailableError as exc:
        return _unavailable(exc)


@router.get("/admin/imports")
def admin_imports(
    request: Request,
    limit: int = Query(10, ge=1, le=50),
) -> Any:
    """Recent import runs (read-only, contains no secrets)."""
    store = request.app.state.store
    return {"imports": store.import_runs(limit=limit)}


# --------------------------------------------------------------------------- #
def _cutoff_dict(policy: CutoffPolicy) -> dict[str, Any]:
    return {
        "time": policy.cutoff_time.strftime("%H:%M"),
        "day_offset": policy.day_offset,
        "timezone": policy.timezone_name,
        "label": policy.label,
        "description": policy.description,
    }


def _metrics_dict(metrics: Any) -> dict[str, Any]:
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


def _coverage_dict(result: AnalysisResult) -> dict[str, Any]:
    return {
        "expected": result.expected_intervals,
        "matched": result.matched,
        "coverage_pct": result.coverage_pct,
        "status_counts": result.status_counts,
    }


def _interval_rows(result: AnalysisResult) -> list[dict[str, Any]]:
    matched = [o for o in result.observations if o.status == "matched"]
    abs_errors = sorted(o.absolute_error_mw for o in matched)
    threshold = None
    if len(abs_errors) >= 8:
        idx = max(0, int(round(0.9 * (len(abs_errors) - 1))))
        threshold = abs_errors[idx]

    tz = ZoneInfo(result.cutoff.timezone_name)
    rows: list[dict[str, Any]] = []
    for index, obs in enumerate(result.observations):
        extreme = bool(
            threshold is not None
            and obs.absolute_error_mw is not None
            and obs.absolute_error_mw >= threshold
            and obs.absolute_error_mw > 0
        )
        rows.append(
            {
                "start_utc": obs.start_time.isoformat(),
                "start_local": obs.start_time.astimezone(tz).strftime("%Y-%m-%d %H:%M"),
                "delivery_date": obs.delivery_date,
                "slot": index,
                "status": obs.status,
                "forecast_mw": obs.forecast_mw,
                "actual_mw": obs.actual_mw,
                "publish_time": (
                    obs.selected_publish_time.isoformat()
                    if obs.selected_publish_time
                    else None
                ),
                "forecast_source_start": (
                    obs.forecast_source_start.isoformat()
                    if obs.forecast_source_start
                    else None
                ),
                "decision_cutoff": obs.decision_cutoff.isoformat(),
                "error_mw": obs.error_mw,
                "absolute_error_mw": obs.absolute_error_mw,
                "squared_error_mw2": obs.squared_error_mw2,
                "exclusion_reason": obs.exclusion_reason,
                "is_extreme_error": extreme,
            }
        )
    return rows


def _forecast_notes(result: AnalysisResult) -> list[str]:
    notes = [
        "WINDFOR publishes one value per hour; the hourly forecast is shown against each "
        "of the two half-hourly intervals it spans.",
        f"Decision cutoff applied: {result.cutoff.label}. {result.cutoff.description}",
    ]
    if result.excluded_after_cutoff:
        notes.append(
            f"{result.excluded_after_cutoff} interval(s) had forecast publications but "
            "every candidate was published after the cutoff, so no forecast was used."
        )
    if not result.selected_publish_times:
        notes.append("No eligible forecast was found for this delivery date.")
    return notes
