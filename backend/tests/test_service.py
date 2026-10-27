"""Service-level tests: cutoff sensitivity, coverage, provenance, empty data."""

from __future__ import annotations

from datetime import date, time

import pytest

from app.service import AnalysisService
from app.source import DataUnavailableError
from app.db.session import session_scope
from app.store import DatabaseStore
from tests.conftest import actual_rows, forecast_rows, make_store, seed_rows, write_snapshot


def test_default_cutoff_selects_the_1130_publication(service: AnalysisService):
    result = service.analyze(date(2026, 1, 2), date(2026, 1, 2))
    publish_times = set(result.selected_publish_times)
    assert publish_times == {"2026-01-01T11:30:00+00:00"}
    assert all(o.forecast_mw == 9500 for o in result.observations)
    # Nothing published after the cutoff is ever used.
    assert not any("13:00" in p for p in result.selected_publish_times)
    assert all(
        o.selected_publish_time <= o.decision_cutoff for o in result.observations
    )


def test_earlier_delivery_days_use_december_publications(service: AnalysisService):
    """Forecast publication history must extend before January."""
    result = service.analyze(date(2026, 1, 1), date(2026, 1, 1))
    assert set(result.selected_publish_times) == {"2025-12-31T11:30:00+00:00"}


def test_changing_the_cutoff_changes_selection_and_metrics(service: AnalysisService):
    default = service.analyze(date(2026, 1, 2), date(2026, 1, 2))
    earlier = service.analyze(
        date(2026, 1, 2),
        date(2026, 1, 2),
        service.resolve_cutoff("10:00"),
    )
    much_earlier = service.analyze(
        date(2026, 1, 2),
        date(2026, 1, 2),
        service.resolve_cutoff("09:00"),
    )
    assert default.observations[0].forecast_mw == 9500
    assert earlier.observations[0].forecast_mw == 9200
    assert much_earlier.observations[0].forecast_mw == 9000
    # Different selection -> different metrics (not merely a relabelled chart).
    assert default.metrics.mae != earlier.metrics.mae


def test_delivery_day_cutoff_admits_the_afternoon_publication(service: AnalysisService):
    policy = service.resolve_cutoff("14:00", cutoff_offset_days=0)
    result = service.analyze(date(2026, 1, 2), date(2026, 1, 2), policy)
    assert result.observations[0].forecast_mw == 9900
    assert set(result.selected_publish_times) == {"2026-01-01T13:00:00+00:00"}


def test_metrics_are_hand_checkable(service: AnalysisService):
    result = service.analyze(date(2026, 1, 1), date(2026, 1, 2))
    # forecast 9500 vs actuals 8000/8500/9000/9500 repeating
    assert result.metrics.mae == pytest.approx(750.0)
    assert result.metrics.bias == pytest.approx(750.0)
    assert result.metrics.rmse == pytest.approx((875000) ** 0.5)
    assert result.metrics.n == 96


def test_coverage_counts_missing_actuals_explicitly(service: AnalysisService):
    result = service.analyze(date(2026, 1, 1), date(2026, 1, 3))
    assert result.expected_intervals == 144
    assert result.matched == 96
    assert result.status_counts["missing_actual"] == 48
    assert result.coverage_pct == pytest.approx(100.0 * 96 / 144)
    # Missing values are never converted into zeroes.
    day_three = [o for o in result.observations if o.delivery_date == "2026-01-03"]
    assert all(o.actual_mw is None for o in day_three)
    assert all(o.error_mw is None for o in day_three)


def test_daily_breakdown_uses_the_same_selection_rules(service: AnalysisService):
    result = service.analyze(date(2026, 1, 1), date(2026, 1, 3))
    assert len(result.daily) == 3
    assert result.daily[0]["n"] == 48
    assert result.daily[0]["mae_mw"] == pytest.approx(750.0)
    assert result.daily[2]["n"] == 0
    assert result.daily[2]["mae_mw"] is None
    assert result.daily[2]["matched"] == 0


def test_overview_reports_provenance_and_derived_summary(service: AnalysisService):
    overview = service.overview()
    assert overview["coverage"]["matched"] == 96
    assert overview["metrics"]["mae_mw"] == pytest.approx(750.0)
    assert "overestimate" in overview["summary"] or "underestimate" in overview["summary"]
    assert overview["provenance"]["origin"] == "database"
    assert overview["provenance"]["retrieved_at"]
    assert overview["cutoff"]["time"] == "12:00"
    assert overview["series"]  # chart data derived from matched intervals


def test_data_quality_explains_exclusions(service: AnalysisService):
    quality = service.data_quality()
    assert quality["coverage"]["expected"] == 144
    # Every interval has an eligible publication under the default cutoff, so
    # nothing is dropped for being late; later publications are simply ignored.
    assert quality["late_forecast_excluded_intervals"] == 0
    assert quality["distinct_selected_publish_times"] == 3
    assert quality["provenance"]["actual_records"] == 96
    assert quality["interval_reasons"] == {
        "actual_generation_unavailable_for_interval": 48
    }


def test_invalid_cutoff_parameters_are_rejected(service: AnalysisService):
    with pytest.raises(ValueError):
        service.resolve_cutoff("25:00")
    with pytest.raises(ValueError):
        service.resolve_cutoff("12")
    with pytest.raises(ValueError):
        service.resolve_cutoff("12:60")


def test_invalid_offset_is_rejected(service: AnalysisService):
    with pytest.raises(ValueError):
        service.resolve_cutoff(None, cutoff_offset_days=-2)


def test_reversed_date_range_is_rejected(service: AnalysisService):
    with pytest.raises(ValueError):
        service.analyze(date(2026, 1, 5), date(2026, 1, 1))


def test_empty_database_never_produces_zero_metrics(tmp_path):
    from app.config import Settings

    settings = Settings(
        eval_start=date(2026, 1, 1),
        eval_end=date(2026, 1, 2),
        snapshot_dir=tmp_path / "snap",
        database_url=f"sqlite:///{(tmp_path / 'empty.db').as_posix()}",
        enable_live_fetch=False,
        seed_on_startup=False,
    )
    store = make_store(settings)  # schema present, no observations
    service = AnalysisService(settings, store=store)
    with pytest.raises(DataUnavailableError):
        service.analyze(date(2026, 1, 1), date(2026, 1, 2))


def test_startup_seeds_an_empty_database_from_the_committed_snapshot(tmp_path):
    """First boot with an empty DB imports the snapshot and says so."""
    from app.config import Settings
    from app.importer import ensure_history

    settings = Settings(
        eval_start=date(2026, 1, 1),
        eval_end=date(2026, 1, 2),
        snapshot_dir=tmp_path / "snap",
        database_url=f"sqlite:///{(tmp_path / 'seeded.db').as_posix()}",
        enable_live_fetch=False,
        seed_on_startup=True,
    )
    write_snapshot(settings, "fuelhh", actual_rows(days=(1, 2)))
    write_snapshot(settings, "windfor", forecast_rows(days=(1, 2)))

    store = make_store(settings)
    with session_scope(store.session_factory) as session:
        ready, message = ensure_history(session, settings, seed_if_missing=True)
    assert ready is True
    assert "initial import completed" in message

    service = AnalysisService(settings, store=store)
    overview = service.overview()
    assert overview["coverage"]["matched"] == 96
    assert overview["provenance"]["origin"] == "database"
    assert any("snapshot" in w["message"].lower() for w in overview["warnings"])


def test_analytics_serve_from_the_database_without_any_upstream_call(tmp_path):
    """No Elexon request is made when serving persisted observations."""
    from app.config import Settings

    settings = Settings(
        eval_start=date(2026, 1, 1),
        eval_end=date(2026, 1, 2),
        snapshot_dir=tmp_path / "snap",
        database_url=f"sqlite:///{(tmp_path / 'serve.db').as_posix()}",
        enable_live_fetch=False,
        seed_on_startup=False,
    )
    store = seed_rows(settings, actual_rows(), forecast_rows(days=(1, 2)))
    service = AnalysisService(settings, store=store)

    calls = {"n": 0}
    original = store.load

    def counting_load(force_refresh: bool = False):
        calls["n"] += 1
        return original(force_refresh=force_refresh)

    store.load = counting_load  # type: ignore[method-assign]
    assert service.analyze(date(2026, 1, 1), date(2026, 1, 2)).metrics.mae == pytest.approx(750.0)
    assert service.analyze(date(2026, 1, 1), date(2026, 1, 2)).metrics.mae == pytest.approx(750.0)
    # Memoised: the store is read once, not per request.
    assert calls["n"] == 1
