"""Durability: import, idempotency, status tracking, restarts and migrations.

Elexon responses are mocked; no live network access is required.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.db import repository
from app.db.migrations import current_revision, schema_exists, upgrade_head
from app.db.session import build_engine, session_scope
from app.elexon.client import ElexonClient
from app.elexon.normalize import normalize_actual, normalize_collection
from app.importer import (
    ensure_history,
    import_actuals,
    import_evaluation_period,
    import_forecasts,
)
from app.service import AnalysisService
from app.source import DataUnavailableError
from app.store import DatabaseStore
from tests.conftest import actual_rows, forecast_rows, make_store, seed_rows, write_snapshot

UTC = timezone.utc


def mock_client(handler) -> ElexonClient:
    return ElexonClient(
        "https://example.test/bmrs/api/v1",
        timeout=5,
        max_retries=2,
        backoff_seconds=0,
        window_days=15,
        transport=httpx.MockTransport(handler),
        sleep=lambda _s: None,
    )


def fuelhh_handler(rows):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/datasets/FUELHH/stream")
        assert "settlementDateFrom" in request.url.params
        return httpx.Response(200, json=rows)

    return handler


def windfor_handler(rows):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/datasets/WINDFOR/stream")
        low = request.url.params.get("publishDateTimeFrom", "")
        high = request.url.params.get("publishDateTimeTo", "")
        filtered = [
            row for row in rows if low <= row["publishTime"] <= high
        ]
        return httpx.Response(200, json=filtered)

    return handler


# --------------------------------------------------------------------------- #
# Import behaviour
# --------------------------------------------------------------------------- #
def test_initial_import_from_the_live_api_with_mocked_responses(settings: Settings):
    store = make_store(settings)

    with session_scope(store.session_factory) as session:
        actual_result = import_actuals(
            session,
            settings,
            client=mock_client(fuelhh_handler(actual_rows(days=(1, 2, 3)))),
        )
        forecast_result = import_forecasts(
            session,
            settings,
            publish_from=datetime(2025, 12, 1, tzinfo=UTC),
            publish_to=datetime(2026, 2, 1, tzinfo=UTC),
            client=mock_client(windfor_handler(forecast_rows(days=(1, 2, 3)))),
        )

    assert actual_result.status == "completed"
    assert actual_result.records_inserted == 144
    assert actual_result.coverage_verified is True
    assert forecast_result.status == "completed"
    assert forecast_result.records_inserted == 3 * 4 * 24
    assert forecast_result.coverage_verified is True

    with session_scope(store.session_factory) as session:
        assert repository.count_actuals(session) == 144
        assert repository.count_forecasts(session) == 288
        runs = repository.latest_imports(session)
        assert len(runs) == 2
        assert all(run.status == "completed" for run in runs)


def test_repeated_import_does_not_create_duplicates(settings: Settings):
    store = make_store(settings)
    client = mock_client(fuelhh_handler(actual_rows(days=(1, 2, 3))))
    with session_scope(store.session_factory) as session:
        first = import_actuals(session, settings, client=client)
    with session_scope(store.session_factory) as session:
        second = import_actuals(
            session, settings, client=mock_client(fuelhh_handler(actual_rows(days=(1, 2, 3))))
        )

    assert first.records_inserted == 144
    assert second.records_inserted == 0
    with session_scope(store.session_factory) as session:
        assert repository.count_actuals(session) == 144


def test_forecast_publication_versions_are_never_merged(settings: Settings):
    store = make_store(settings)
    rows = forecast_rows(days=(2,))
    with session_scope(store.session_factory) as session:
        import_forecasts(
            session,
            settings,
            publish_from=datetime(2025, 12, 1, tzinfo=UTC),
            publish_to=datetime(2026, 2, 1, tzinfo=UTC),
            client=mock_client(windfor_handler(rows)),
        )
    with session_scope(store.session_factory) as session:
        forecasts = repository.load_forecasts(session)

    # 4 publications x 24 hours for one delivery day
    assert len(forecasts) == 96
    publish_times = {f.publish_time for f in forecasts}
    assert len(publish_times) == 4
    # publishTime and startTime stay distinct, exactly as the source reports them
    for record in forecasts:
        assert record.publish_time != record.start_time


def test_actual_revision_policy_prefers_the_latest_publish_time(settings: Settings):
    store = make_store(settings)
    older = actual_rows(days=(1,))[0]
    newer = dict(older, generation=12345, publishTime="2026-01-05T00:30:00Z")
    stale = dict(older, generation=1111, publishTime="2025-12-30T00:30:00Z")

    with session_scope(store.session_factory) as session:
        import_actuals(session, settings, client=mock_client(fuelhh_handler([older])))
    with session_scope(store.session_factory) as session:
        # An older revision must not clobber the stored value...
        import_actuals(session, settings, client=mock_client(fuelhh_handler([stale])))
    with session_scope(store.session_factory) as session:
        assert repository.load_actuals(session)[0].generation_mw == older["generation"]
        # ...while a newer revision updates it in place.
        import_actuals(session, settings, client=mock_client(fuelhh_handler([newer])))
    with session_scope(store.session_factory) as session:
        assert repository.load_actuals(session)[0].generation_mw == 12345


def test_failed_windows_produce_a_partial_run_not_a_completed_one(settings: Settings):
    store = make_store(settings)
    rows = actual_rows()

    def flaky(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("settlementDateFrom") == "2026-01-02":
            return httpx.Response(503, text="upstream down")
        return httpx.Response(200, json=rows)

    # One-day windows split the 3-day range into three fetches.
    from dataclasses import replace

    settings_small = replace(settings, elexon_window_days=1)
    with session_scope(store.session_factory) as session:
        result = import_actuals(
            session,
            settings_small,
            client=mock_client(flaky),
        )

    assert result.status == "partial"
    assert result.windows_total == 3
    assert result.windows_ok == 2
    assert len(result.windows_failed) == 1
    assert result.coverage_verified is False
    assert "2026-01-02" in result.windows_failed[0]

    with session_scope(store.session_factory) as session:
        runs = repository.latest_imports(session, dataset="FUELHH")
        assert runs[0].status == "partial"
        assert runs[0].coverage_verified is False
        # The two successful windows are still stored: partial, not wasted.
        assert repository.count_actuals(session) == 96


def test_retry_after_failure_completes_the_history(settings: Settings):
    store = make_store(settings)
    rows = actual_rows(days=(1, 2, 3))

    def broken(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    with session_scope(store.session_factory) as session:
        failed = import_actuals(session, settings, client=mock_client(broken))
    assert failed.status == "failed"

    with session_scope(store.session_factory) as session:
        retried = import_actuals(session, settings, client=mock_client(fuelhh_handler(rows)))
    assert retried.status == "completed"
    with session_scope(store.session_factory) as session:
        assert repository.count_actuals(session) == 144
        runs = repository.latest_imports(session, dataset="FUELHH")
        assert [run.status for run in runs] == ["completed", "failed"]


def test_snapshot_seeding_marks_the_run_source(settings: Settings):
    write_snapshot(settings, "fuelhh", actual_rows(days=(1, 2, 3)))
    write_snapshot(settings, "windfor", forecast_rows(days=(1, 2, 3)))
    store = make_store(settings)

    with session_scope(store.session_factory) as session:
        ready, message = ensure_history(session, settings, seed_if_missing=True)
    assert ready is True

    with session_scope(store.session_factory) as session:
        runs = repository.latest_imports(session)
        assert {run.source for run in runs} == {"snapshot"}
        assert all(run.status == "completed" for run in runs)
    assert "initial import completed" in message


def test_ensure_history_reports_missing_data_without_seeding(settings: Settings):
    settings = settings.with_database_url(settings.database_url)
    store = make_store(settings)
    with session_scope(store.session_factory) as session:
        ready, message = ensure_history(session, settings, seed_if_missing=False)
    assert ready is False
    assert "import" in message


# --------------------------------------------------------------------------- #
# Reading persisted data
# --------------------------------------------------------------------------- #
def test_persisted_records_survive_a_process_restart(settings: Settings):
    store = seed_rows(settings, actual_rows(), forecast_rows(days=(1, 2, 3)))
    with session_scope(store.session_factory) as session:
        before_actuals = repository.count_actuals(session)
        before_forecasts = repository.count_forecasts(session)
        first_publish = repository.load_forecasts(session)[0].publish_time

    # A brand new engine/store pair simulates a restarted backend process.
    restarted = DatabaseStore(settings)
    with session_scope(restarted.session_factory) as session:
        assert repository.count_actuals(session) == before_actuals
        assert repository.count_forecasts(session) == before_forecasts
        assert repository.load_forecasts(session)[0].publish_time == first_publish

    overview = AnalysisService(settings, store=restarted).overview()
    assert overview["coverage"]["matched"] == 96
    assert overview["metrics"]["mae_mw"] == pytest.approx(750.0)


def test_metrics_are_computed_from_persisted_observations(settings: Settings):
    store = seed_rows(settings, actual_rows(), forecast_rows(days=(1, 2, 3)))
    service = AnalysisService(settings, store=store)
    result = service.analyze(date(2026, 1, 1), date(2026, 1, 2))
    assert result.metrics.n == 96
    assert result.metrics.mae == pytest.approx(750.0)
    assert result.metrics.rmse == pytest.approx(875000**0.5)
    assert result.metrics.bias == pytest.approx(750.0)
    assert result.metrics.mape is not None


def test_forecast_selection_uses_persisted_publication_times(settings: Settings):
    store = seed_rows(settings, actual_rows(), forecast_rows(days=(2,)))
    service = AnalysisService(settings, store=store)
    default = service.analyze(date(2026, 1, 2), date(2026, 1, 2))
    earlier = service.analyze(date(2026, 1, 2), date(2026, 1, 2), service.resolve_cutoff("10:00"))
    assert set(default.selected_publish_times) == {"2026-01-01T11:30:00+00:00"}
    assert default.observations[0].forecast_mw == 9500
    assert earlier.observations[0].forecast_mw == 9200


def test_refresh_invalidates_the_in_process_cache(settings: Settings):
    store = seed_rows(settings, actual_rows(days=(1,)), forecast_rows(days=(1, 2)))
    service = AnalysisService(settings, store=store)
    assert service.analyze(date(2026, 1, 1), date(2026, 1, 1)).metrics.n == 48

    # A later import extends the history; the memo must not hide it.
    extra, _ = normalize_collection(actual_rows(days=(2,)), normalize_actual, "FUELHH")
    with session_scope(store.session_factory) as session:
        repository.upsert_actuals(session, extra)
    store.invalidate()
    assert service.analyze(date(2026, 1, 2), date(2026, 1, 2)).metrics.n == 48


def test_store_raises_when_the_database_is_empty(settings: Settings):
    store = make_store(settings)
    with pytest.raises(DataUnavailableError):
        store.load()


def test_store_raises_when_the_database_is_unreachable(settings: Settings):
    broken = Settings(
        eval_start=settings.eval_start,
        eval_end=settings.eval_end,
        snapshot_dir=settings.snapshot_dir,
        database_url="sqlite:///%2Froot%2Fforbidden%2Fwindsight.db",
        seed_on_startup=False,
    )
    store = DatabaseStore(broken)
    with pytest.raises(Exception):
        store.load()


def test_concurrent_imports_are_refused(settings: Settings):
    store = seed_rows(settings, actual_rows(), forecast_rows(days=(2,)))
    with session_scope(store.session_factory) as session:
        repository.record_import_start(
            session,
            dataset="FUELHH",
            range_start=datetime(2026, 1, 1, tzinfo=UTC),
            range_end=datetime(2026, 1, 31, tzinfo=UTC),
        )
    with pytest.raises(RuntimeError):
        store.run_import(source="snapshot")


# --------------------------------------------------------------------------- #
# Schema management
# --------------------------------------------------------------------------- #
def test_migrations_create_the_schema_on_a_fresh_database(tmp_path: Path):
    url = f"sqlite:///{(tmp_path / 'migrated.db').as_posix()}"
    assert schema_exists(url) is False
    upgrade_head(url)
    assert schema_exists(url) is True
    assert current_revision(url) is not None

    engine = build_engine(url)
    from sqlalchemy import inspect

    tables = set(inspect(engine).get_table_names())
    assert {"actual_generation", "wind_forecasts", "data_import_runs"} <= tables


def test_migrations_are_idempotent(tmp_path: Path):
    url = f"sqlite:///{(tmp_path / 'twice.db').as_posix()}"
    first = upgrade_head(url)
    second = upgrade_head(url)
    assert first == second


def test_production_without_database_url_refuses_sqlite_fallback():
    from app.db.session import resolve_database_url

    with pytest.raises(RuntimeError):
        resolve_database_url("", allow_sqlite_default=False)


def test_provider_postgres_urls_use_the_installed_psycopg_driver():
    """Render/Supabase hand out postgresql:// and Heroku postgres://."""
    from app.db.session import resolve_database_url

    assert (
        resolve_database_url("postgres://u:p@host:5432/db")
        == "postgresql+psycopg://u:p@host:5432/db"
    )
    assert (
        resolve_database_url("postgresql://u:p@host:5432/db?sslmode=require")
        == "postgresql+psycopg://u:p@host:5432/db?sslmode=require"
    )
    # Already-explicit URLs are left untouched.
    assert (
        resolve_database_url("postgresql+psycopg://u:p@host:5432/db")
        == "postgresql+psycopg://u:p@host:5432/db"
    )
