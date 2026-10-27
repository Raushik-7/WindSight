"""Fetch the evaluation-period datasets from Elexon and write snapshots.

Usage (from ``backend/``):

    python scripts/fetch_snapshots.py

The resulting JSON files land in ``backend/data/snapshots/`` and are committed
to the repository so that the analysis is reproducible without live API access
and so the demo starts instantly.  They contain real Elexon records only -
no synthetic values are ever written.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.config import Settings  # noqa: E402
from app.elexon.client import ElexonClient  # noqa: E402
from app.source import _write_payload  # noqa: E402


def main() -> int:
    settings = Settings.from_env()
    settings.snapshot_dir.mkdir(parents=True, exist_ok=True)

    publish_from = datetime.combine(
        settings.eval_start - timedelta(days=settings.forecast_history_days),
        datetime.min.time(),
        tzinfo=timezone.utc,
    )
    publish_to = datetime.combine(
        settings.eval_end + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc
    ) - timedelta(seconds=1)

    client = ElexonClient(
        settings.elexon_base_url,
        timeout=settings.elexon_timeout_seconds,
        max_retries=settings.elexon_max_retries,
        backoff_seconds=settings.elexon_backoff_seconds,
        window_days=settings.elexon_window_days,
    )
    try:
        print(f"Fetching FUELHH {settings.eval_start} -> {settings.eval_end} ...")
        actuals = client.fetch_actuals(settings.eval_start, settings.eval_end)
        print(f"  {len(actuals)} rows")

        print(f"Fetching WINDFOR published {publish_from.date()} -> {publish_to.date()} ...")
        forecasts = client.fetch_forecasts(publish_from, publish_to)
        print(f"  {len(forecasts)} rows")

        retrieved = datetime.now(timezone.utc)
        _write_payload(settings.snapshot_dir / "fuelhh.json", actuals, retrieved)
        _write_payload(settings.snapshot_dir / "windfor.json", forecasts, retrieved)
        print(f"Snapshots written to {settings.snapshot_dir}")
        print(f"Upstream requests issued: {client.request_count}")
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
