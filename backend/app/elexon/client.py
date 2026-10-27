"""HTTP client for the Elexon BMRS API.

Verified against the official OpenAPI specification
(https://data.elexon.co.uk/swagger/v1/swagger.json):

* ``GET /datasets/FUELHH/stream`` accepts ``settlementDateFrom`` /
  ``settlementDateTo`` (``yyyy-MM-dd``) and ``fuelType``.
* ``GET /datasets/WINDFOR/stream`` accepts ``publishDateTimeFrom`` /
  ``publishDateTimeTo`` (ISO-8601 instants).
* Neither endpoint requires an API key.

Large ranges are requested in bounded windows so that a single slow or
oversized upstream response cannot take the whole ingestion down.
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Optional

import httpx

logger = logging.getLogger(__name__)

FUELHH = "FUELHH"
WINDFOR = "WINDFOR"


class UpstreamError(RuntimeError):
    """Raised when the Elexon API cannot be reached or returns garbage."""

    def __init__(self, message: str, *, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _date(d: date) -> str:
    return d.isoformat()


def date_windows(start: date, end: date, max_days: int) -> list[tuple[date, date]]:
    """Split ``[start, end]`` (inclusive) into windows of at most ``max_days``."""
    if start > end:
        return []
    windows: list[tuple[date, date]] = []
    cursor = start
    step = max(1, max_days)
    while cursor <= end:
        window_end = min(cursor + timedelta(days=step - 1), end)
        windows.append((cursor, window_end))
        cursor = window_end + timedelta(days=1)
    return windows


class ElexonClient:
    """Thin, retrying client for the two assignment datasets."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 60.0,
        max_retries: int = 3,
        backoff_seconds: float = 1.5,
        window_days: int = 15,
        transport: Optional[httpx.BaseTransport] = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max(1, max_retries)
        self.backoff_seconds = backoff_seconds
        self.window_days = window_days
        self._sleep = sleep
        self.request_count = 0
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout),
            headers={"Accept": "application/json", "User-Agent": "windsight-analytics/1.0"},
            transport=transport,
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ElexonClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ------------------------------------------------------------------ #
    def _get(self, path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries):
            self.request_count += 1
            try:
                response = self._client.get(path, params=params)
            except httpx.HTTPError as exc:
                last_error = exc
                logger.warning("Elexon request failed (attempt %s): %s", attempt + 1, exc)
                self._sleep(self.backoff_seconds * (attempt + 1))
                continue

            if response.status_code >= 500 or response.status_code == 429:
                last_error = UpstreamError(
                    f"Elexon returned HTTP {response.status_code}",
                    status_code=response.status_code,
                )
                logger.warning("Elexon server error %s (attempt %s)", response.status_code, attempt + 1)
                self._sleep(self.backoff_seconds * (attempt + 1))
                continue

            if response.status_code != 200:
                raise UpstreamError(
                    f"Elexon returned HTTP {response.status_code} for {path}",
                    status_code=response.status_code,
                )

            content_type = response.headers.get("content-type", "")
            if "json" not in content_type:
                raise UpstreamError(
                    f"Unexpected content type from Elexon: {content_type or 'unknown'}"
                )
            try:
                payload = response.json()
            except ValueError as exc:
                raise UpstreamError("Elexon returned a malformed JSON body") from exc

            if not isinstance(payload, list):
                raise UpstreamError(
                    f"Unexpected Elexon response shape: expected a list, got {type(payload).__name__}"
                )
            return [row for row in payload if isinstance(row, dict)]

        raise UpstreamError(
            f"Elexon request failed after {self.max_retries} attempts: {last_error}"
        )

    # ------------------------------------------------------------------ #
    def fetch_actuals(self, start: date, end: date) -> list[dict[str, Any]]:
        """FUELHH half-hourly outturn, wind only, for a delivery-date range."""
        rows: list[dict[str, Any]] = []
        for window_start, window_end in date_windows(start, end, self.window_days):
            rows.extend(
                self._get(
                    f"/datasets/{FUELHH}/stream",
                    {
                        "settlementDateFrom": _date(window_start),
                        "settlementDateTo": _date(window_end),
                        "fuelType": "WIND",
                    },
                )
            )
        return rows

    def fetch_forecasts(self, publish_from: datetime, publish_to: datetime) -> list[dict[str, Any]]:
        """WINDFOR published forecasts for a *publication*-time range."""
        rows: list[dict[str, Any]] = []
        cursor = publish_from
        step = timedelta(days=self.window_days)
        while cursor <= publish_to:
            window_end = min(cursor + step, publish_to)
            rows.extend(
                self._get(
                    f"/datasets/{WINDFOR}/stream",
                    {
                        "publishDateTimeFrom": _iso(cursor),
                        "publishDateTimeTo": _iso(window_end),
                    },
                )
            )
            cursor = window_end + timedelta(seconds=1)
        return rows
