"""CSV export of the analytical dataset.

Export always reflects the exact observations used for the metrics, including
rows that could not be matched, so nothing is silently omitted.  Cells that
could be interpreted as spreadsheet formulas are neutralised.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Iterable, Optional

from .models import MatchedObservation

HEADERS = [
    "delivery_interval_start_utc",
    "delivery_interval_local",
    "delivery_date",
    "decision_cutoff_utc",
    "selected_forecast_publish_time_utc",
    "forecast_source_interval_utc",
    "forecast_mw",
    "actual_mw",
    "error_mw",
    "absolute_error_mw",
    "squared_error_mw2",
    "match_status",
    "exclusion_reason",
]

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def neutralise(value: object) -> str:
    """Render a value for CSV, defusing spreadsheet formula injection.

    Numeric values keep their sign (``-123`` is a number, not a formula).
    """
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if text.startswith(_FORMULA_PREFIXES):
        try:
            float(text)
        except ValueError:
            return "'" + text
    return text


def _iso(value: Optional[datetime]) -> str:
    return value.isoformat() if value else ""


def observations_to_rows(observations: Iterable[MatchedObservation]) -> list[list[str]]:
    rows: list[list[str]] = []
    for obs in observations:
        rows.append(
            [
                _iso(obs.start_time),
                _iso(obs.start_time),
                obs.delivery_date,
                _iso(obs.decision_cutoff),
                _iso(obs.selected_publish_time),
                _iso(obs.forecast_source_start),
                neutralise(obs.forecast_mw),
                neutralise(obs.actual_mw),
                neutralise(obs.error_mw),
                neutralise(obs.absolute_error_mw),
                neutralise(obs.squared_error_mw2),
                obs.status,
                obs.exclusion_reason or "",
            ]
        )
    return rows


def observations_to_csv(observations: Iterable[MatchedObservation]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(HEADERS)
    for row in observations_to_rows(observations):
        writer.writerow(row)
    return buffer.getvalue()


def export_filename(date_from: str, date_to: str) -> str:
    def clean(value: str) -> str:
        return "".join(ch for ch in value if ch.isalnum() or ch in "-_")

    return f"windsight_{clean(date_from)}_{clean(date_to)}.csv"
