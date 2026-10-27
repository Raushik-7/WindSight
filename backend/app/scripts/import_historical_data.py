"""Import Elexon history into the durable database.

Usage (from ``backend/``)::

    # Apply the schema, then import the evaluation period from the live API
    python -m app.scripts.import_historical_data --from 2026-01-01 --to 2026-01-31

    # Seed from the committed real-data snapshots (offline, deterministic)
    python -m app.scripts.import_historical_data --from 2026-01-01 --to 2026-01-31 --source snapshot

    # Inspect what is already stored
    python -m app.scripts.import_historical_data --status

The command is safe to re-run: writes are idempotent upserts keyed on the
verified source identities, and each attempt is recorded in
``data_import_runs`` with an honest status (completed / partial / failed).
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from ..config import Settings
from ..db import repository
from ..db.session import (
    build_engine,
    create_session_factory,
    database_kind,
    resolve_database_url,
    session_scope,
)
from ..importer import (
    DatasetImportResult,
    import_actuals,
    import_forecasts,
    result_to_dict,
)

UTC = timezone.utc


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.scripts.import_historical_data",
        description="Import Elexon FUELHH/WINDFOR history into durable storage.",
    )
    parser.add_argument("--from", dest="date_from", type=_parse_date, help="Delivery date (yyyy-mm-dd)")
    parser.add_argument("--to", dest="date_to", type=_parse_date, help="Delivery date (yyyy-mm-dd)")
    parser.add_argument(
        "--source",
        choices=["live", "snapshot"],
        default="live",
        help="live = Elexon BMRS API, snapshot = committed real-data snapshot",
    )
    parser.add_argument(
        "--upgrade-schema",
        action="store_true",
        help="Run 'alembic upgrade head' before importing.",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print stored counts and recent import runs, then exit.",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Override DATABASE_URL (defaults to the environment / SQLite file).",
    )
    return parser


def run_upgrade_schema(database_url: str) -> None:
    from ..db.migrations import upgrade_head

    upgrade_head(database_url)


def print_status(settings: Settings, session_factory) -> int:
    with session_scope(session_factory) as session:
        actuals = repository.count_actuals(session)
        forecasts = repository.count_forecasts(session)
        low, high = repository.forecast_publication_range(session)
        coverage = repository.coverage_snapshot(session, settings.eval_start, settings.eval_end)
        runs = repository.latest_imports(session, limit=10)

    print(f"Database           : {settings.database_url}")
    print(f"Kind               : {database_kind(settings.database_url)}")
    print(f"Actual records     : {actuals}")
    print(f"Forecast records   : {forecasts}")
    print(f"Forecast published : {low} .. {high}")
    print(
        f"Delivery coverage  : {coverage['present']}/{coverage['expected']} half-hourly intervals"
    )
    if runs:
        print("\nRecent import runs:")
        header = f"{'id':>4} {'dataset':<8} {'source':<10} {'status':<10} {'retrieved':>9} {'ins':>7} {'upd':>7} {'windows':>9} {'coverage':>9}"
        print(header)
        for run in runs:
            print(
                f"{run.id:>4} {run.dataset:<8} {run.source:<10} {run.status:<10} "
                f"{run.records_retrieved:>9} {run.records_inserted:>7} {run.records_updated:>7} "
                f"{run.windows_ok:>4}/{run.windows_total:<4} {str(run.coverage_verified):>9}"
            )
            if run.error_detail:
                print(f"     error: {run.error_detail}")
            if run.coverage_detail:
                print(f"     coverage: {run.coverage_detail}")
    else:
        print("\nNo import runs recorded yet.")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings.from_env()
    if args.database_url:
        settings = settings.with_database_url(args.database_url)

    database_url = resolve_database_url(
        settings.database_url, allow_sqlite_default=True
    )
    engine = build_engine(database_url)
    session_factory = create_session_factory(engine)

    if args.upgrade_schema:
        print(f"Applying schema migrations to {database_url} ...")
        run_upgrade_schema(database_url)

    if args.status:
        return print_status(settings, session_factory)

    date_from = args.date_from or settings.eval_start
    date_to = args.date_to or settings.eval_end
    if date_from > date_to:
        print("--from must not be after --to", file=sys.stderr)
        return 2

    publish_from = datetime.combine(
        date_from - timedelta(days=settings.forecast_history_days),
        datetime.min.time(),
        tzinfo=UTC,
    )
    publish_to = datetime.combine(date_to + timedelta(days=1), datetime.min.time(), tzinfo=UTC) - timedelta(
        seconds=1
    )

    results: list[DatasetImportResult] = []
    with session_scope(session_factory) as session:
        results.append(
            import_actuals(
                session, settings, date_from=date_from, date_to=date_to, source=args.source
            )
        )
        results.append(
            import_forecasts(
                session,
                settings,
                publish_from=publish_from,
                publish_to=publish_to,
                source=args.source,
            )
        )

    exit_code = 0
    print(f"Imported into {database_url}")
    for result in results:
        payload = result_to_dict(result)
        print(
            f"  {payload['dataset']:<8} {payload['status']:<10} "
            f"retrieved={payload['records_retrieved']} inserted={payload['records_inserted']} "
            f"updated={payload['records_updated']} skipped={payload['records_skipped']} "
            f"windows={payload['windows_ok']}/{payload['windows_total']} "
            f"coverage_verified={payload['coverage_verified']}"
        )
        print(f"           range {payload['range_start']} -> {payload['range_end']}")
        print(f"           {payload['coverage_detail']}")
        for failure in payload["windows_failed"]:
            print(f"           failed window: {failure}", file=sys.stderr)
        if payload["error_detail"]:
            print(f"           error: {payload['error_detail']}", file=sys.stderr)
        if not result.ok:
            exit_code = 1

    return exit_code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
