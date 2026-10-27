"""Shared fixtures.

The records built here are **test fixtures**, not real measurements: they exist
to exercise cutoff selection, matching, metrics and persistence with
hand-checkable numbers.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Iterable

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.config import Settings  # noqa: E402
from app.db import repository  # noqa: E402
from app.db.migrations import upgrade_head  # noqa: E402
from app.db.session import session_scope  # noqa: E402
from app.elexon.normalize import (  # noqa: E402
    deduplicate_actuals,
    deduplicate_forecasts,
    normalize_collection,
    normalize_actual,
    normalize_forecast,
)
from app.service import AnalysisService  # noqa: E402
from app.store import DatabaseStore  # noqa: E402

EVAL_START = date(2026, 1, 1)
EVAL_END = date(2026, 1, 3)
UTC = timezone.utc


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        eval_start=EVAL_START,
        eval_end=EVAL_END,
        cache_dir=tmp_path / "cache",
        snapshot_dir=tmp_path / "snapshots",
        database_url=f"sqlite:///{(tmp_path / 'windsight.db').as_posix()}",
        enable_live_fetch=False,
        allow_snapshot_fallback=True,
        seed_on_startup=False,
        admin_token="",
    )


def make_store(settings: Settings) -> DatabaseStore:
    """Create a store whose schema comes from the real Alembic migrations."""
    store = DatabaseStore(settings)
    upgrade_head(store.database_url)
    return store


def write_snapshot(settings: Settings, name: str, rows: list[dict]) -> Path:
    """Write a snapshot payload for seeding/import tests."""
    import json

    settings.snapshot_dir.mkdir(parents=True, exist_ok=True)
    path = settings.snapshot_dir / f"{name}.json"
    path.write_text(
        json.dumps(
            {
                "retrieved_at": datetime.now(UTC).isoformat(),
                "row_count": len(rows),
                "rows": rows,
            }
        ),
        encoding="utf-8",
    )
    return path


def seed_rows(
    settings: Settings,
    actuals: Iterable[dict] = (),
    forecasts: Iterable[dict] = (),
    *,
    store: DatabaseStore | None = None,
) -> DatabaseStore:
    """Normalise raw fixture rows and write them durably."""
    store = store or make_store(settings)
    actual_records, _ = normalize_collection(list(actuals), normalize_actual, "FUELHH")
    actual_records, _ = deduplicate_actuals(actual_records)
    forecast_records, _ = normalize_collection(list(forecasts), normalize_forecast, "WINDFOR")
    forecast_records, _ = deduplicate_forecasts(forecast_records)

    with session_scope(store.session_factory) as session:
        repository.upsert_actuals(session, actual_records)
        repository.upsert_forecasts(session, forecast_records)
    store.invalidate()
    return store


def actual_rows(days: Iterable[int] = (1, 2)) -> list[dict]:
    """Half-hourly FUELHH WIND rows: 8000 + (slot % 4) * 500 MW."""
    rows = []
    for day in days:
        for slot in range(48):
            start = datetime(2026, 1, day, 0, 0, tzinfo=UTC) + timedelta(minutes=30 * slot)
            rows.append(
                {
                    "dataset": "FUELHH",
                    "publishTime": (start + timedelta(minutes=30)).isoformat().replace(
                        "+00:00", "Z"
                    ),
                    "startTime": start.isoformat().replace("+00:00", "Z"),
                    "settlementDate": f"2026-01-{day:02d}",
                    "settlementPeriod": slot + 1,
                    "fuelType": "WIND",
                    "generation": 8000 + (slot % 4) * 500,
                }
            )
    return rows


def forecast_rows(days: Iterable[int] = (1, 2)) -> list[dict]:
    """Hourly WINDFOR rows for the fixtures.

    For each delivery day D the publication schedule is:

    * D-2 22:30 -> 9000 MW (older eligible fallback)
    * D-1 09:30 -> 9200 MW
    * D-1 11:30 -> 9500 MW  <- latest eligible under the 12:00 D-1 cutoff
    * D-1 13:00 -> 9900 MW  <- published after the cutoff, must never win
    """
    rows: list[dict] = []
    for day in days:
        delivery = date(2026, 1, day)
        schedule = [
            (delivery - timedelta(days=2), time(22, 30), 9000),
            (delivery - timedelta(days=1), time(9, 30), 9200),
            (delivery - timedelta(days=1), time(11, 30), 9500),
            (delivery - timedelta(days=1), time(13, 0), 9900),
        ]
        for publish_day, publish_time, value in schedule:
            publish = datetime.combine(publish_day, publish_time, tzinfo=UTC)
            for hour in range(24):
                start = datetime.combine(delivery, time(hour, 0), tzinfo=UTC)
                rows.append(
                    {
                        "dataset": "WINDFOR",
                        "publishTime": publish.isoformat().replace("+00:00", "Z"),
                        "startTime": start.isoformat().replace("+00:00", "Z"),
                        "generation": value,
                    }
                )
    return rows


@pytest.fixture
def store(settings: Settings) -> DatabaseStore:
    return make_store(settings)


@pytest.fixture
def populated_store(settings: Settings) -> DatabaseStore:
    return seed_rows(
        settings,
        actual_rows(),
        forecast_rows(days=(1, 2, 3)),
    )


@pytest.fixture
def service(populated_store: DatabaseStore) -> AnalysisService:
    return AnalysisService(populated_store.settings, store=populated_store)
