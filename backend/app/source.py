"""Loading of source records: cache -> live Elexon API -> committed snapshot.

Provenance rules enforced here:

* A successful live fetch is recorded as ``live`` with its retrieval time.
* A cached copy is recorded as ``cache`` with the time it was fetched.
* A committed snapshot is recorded as ``snapshot`` with its own retrieval
  time, and is only used when the live API fails (or is disabled) **and**
  ``ALLOW_SNAPSHOT_FALLBACK`` permits it.

Nothing here ever invents data: if none of the sources is available the load
fails loudly and the API returns an error state instead of empty metrics.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from .config import Settings
from .elexon.client import ElexonClient, UpstreamError
from .models import SourceData
from .elexon.normalize import (
    deduplicate_actuals,
    deduplicate_forecasts,
    normalize_collection,
    normalize_actual,
    normalize_forecast,
)

logger = logging.getLogger(__name__)

DATASET_ACTUALS = "fuelhh"
DATASET_FORECASTS = "windfor"


class DataUnavailableError(RuntimeError):
    """Raised when no source can provide the requested dataset."""


def _read_payload(path: Path) -> Optional[dict[str, Any]]:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not read %s: %s", path, exc)
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("rows"), list):
        return None
    return payload


def _write_payload(path: Path, rows: list[dict[str, Any]], retrieved_at: datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = {
        "retrieved_at": retrieved_at.astimezone(timezone.utc).isoformat(),
        "row_count": len(rows),
        "rows": rows,
    }
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    tmp.replace(path)


def _is_fresh(payload: dict[str, Any], ttl_seconds: int) -> bool:
    raw = payload.get("retrieved_at")
    if not raw:
        return False
    try:
        fetched = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return False
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - fetched).total_seconds()
    return 0 <= age <= ttl_seconds


class DataSource:
    """Thread-safe loader for the two Elexon datasets."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = threading.Lock()
        self._cached: Optional[SourceData] = None
        self.client_factory: Callable[[], ElexonClient] = lambda: ElexonClient(
            settings.elexon_base_url,
            timeout=settings.elexon_timeout_seconds,
            max_retries=settings.elexon_max_retries,
            backoff_seconds=settings.elexon_backoff_seconds,
            window_days=settings.elexon_window_days,
        )

    # ------------------------------------------------------------------ #
    def _paths(self, name: str) -> tuple[Path, Path]:
        return (
            self.settings.cache_dir / f"{name}.json",
            self.settings.snapshot_dir / f"{name}.json",
        )

    def _load_one(
        self,
        name: str,
        fetch: Callable[[ElexonClient], list[dict[str, Any]]],
        errors: list[str],
    ) -> tuple[list[dict[str, Any]], Optional[datetime], str, int]:
        cache_path, snapshot_path = self._paths(name)
        requests_before = 0

        cached = _read_payload(cache_path)
        if cached is not None and _is_fresh(cached, self.settings.cache_ttl_seconds):
            return (
                cached["rows"],
                datetime.fromisoformat(str(cached["retrieved_at"]).replace("Z", "+00:00")),
                "cache",
                requests_before,
            )

        if self.settings.enable_live_fetch:
            client = self.client_factory()
            try:
                rows = fetch(client)
                retrieved = datetime.now(timezone.utc)
                requests_before = client.request_count
                _write_payload(cache_path, rows, retrieved)
                return rows, retrieved, "live", requests_before
            except UpstreamError as exc:
                errors.append(f"{name}: {exc}")
                logger.warning("Live fetch failed for %s: %s", name, exc)
            finally:
                client.close()

        stale = _read_payload(cache_path)
        if stale is not None:
            return (
                stale["rows"],
                datetime.fromisoformat(str(stale["retrieved_at"]).replace("Z", "+00:00")),
                "cache_stale",
                requests_before,
            )

        if self.settings.allow_snapshot_fallback:
            snapshot = _read_payload(snapshot_path)
            if snapshot is not None:
                return (
                    snapshot["rows"],
                    datetime.fromisoformat(str(snapshot["retrieved_at"]).replace("Z", "+00:00")),
                    "snapshot",
                    requests_before,
                )

        raise DataUnavailableError(
            f"No source available for dataset '{name}': upstream failed and no "
            "cache or snapshot exists."
        )

    # ------------------------------------------------------------------ #
    def load(self, force_refresh: bool = False) -> SourceData:
        with self._lock:
            if self._cached is not None and not force_refresh:
                return self._cached

            settings = self.settings
            errors: list[str] = []
            requests = 0

            def fetch_actuals(client: ElexonClient) -> list[dict[str, Any]]:
                return client.fetch_actuals(settings.eval_start, settings.eval_end)

            publish_from = datetime.combine(
                settings.eval_start - timedelta(days=settings.forecast_history_days),
                datetime.min.time(),
                tzinfo=timezone.utc,
            )
            publish_to = datetime.combine(
                settings.eval_end + timedelta(days=1),
                datetime.min.time(),
                tzinfo=timezone.utc,
            ) - timedelta(seconds=1)

            def fetch_forecasts(client: ElexonClient) -> list[dict[str, Any]]:
                return client.fetch_forecasts(publish_from, publish_to)

            actual_rows, actual_at, actual_origin, n1 = self._load_one(
                DATASET_ACTUALS, fetch_actuals, errors
            )
            forecast_rows, forecast_at, forecast_origin, n2 = self._load_one(
                DATASET_FORECASTS, fetch_forecasts, errors
            )
            requests = n1 + n2

            actuals, actual_exclusions = normalize_collection(
                actual_rows, normalize_actual, "FUELHH"
            )
            forecasts, forecast_exclusions = normalize_collection(
                forecast_rows, normalize_forecast, "WINDFOR"
            )
            actuals, actual_dupes = deduplicate_actuals(actuals)
            forecasts, forecast_dupes = deduplicate_forecasts(forecasts)

            origins = {actual_origin, forecast_origin}
            if origins == {"live"}:
                origin = "live"
            elif "live" in origins:
                origin = "mixed"
            elif origins <= {"cache", "cache_stale"}:
                origin = "cache"
            elif origins <= {"cache", "cache_stale", "snapshot"}:
                origin = "snapshot"
            else:
                origin = "mixed"

            retrieved_at = max(
                [t for t in (actual_at, forecast_at) if t is not None], default=None
            )

            source = SourceData(
                actuals=actuals,
                forecasts=forecasts,
                retrieved_at=retrieved_at,
                origin=origin,
                origin_detail=(
                    f"actuals={actual_origin} ({len(actual_rows)} rows), "
                    f"forecasts={forecast_origin} ({len(forecast_rows)} rows)"
                ),
                exclusions=actual_exclusions + forecast_exclusions + actual_dupes + forecast_dupes,
                fetch_errors=errors,
                upstream_requests=requests,
            )
            self._cached = source
            return source

    def invalidate(self) -> None:
        with self._lock:
            self._cached = None
