"""Integration tests for the application API (mocked upstream, no live calls)."""

from __future__ import annotations

from datetime import date, datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.conftest import actual_rows, forecast_rows, make_store, seed_rows, write_snapshot


@pytest.fixture
def client(populated_store) -> TestClient:
    # create_app builds its own store against the same DATABASE_URL, so the
    # seeded fixture database is what the API actually reads.
    app = create_app(populated_store.settings)
    with TestClient(app) as test_client:
        yield test_client


def test_health_reports_data_readiness(client: TestClient):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["data"]["actual_records"] == 96
    assert body["data"]["forecast_records"] == 288
    assert body["cutoff"]["time"] == "12:00"


def test_overview_returns_computed_metrics_and_provenance(client: TestClient):
    response = client.get("/api/overview")
    assert response.status_code == 200
    body = response.json()
    assert body["period"]["start"] == "2026-01-01"
    assert body["period"]["expected_intervals"] == 144
    assert body["metrics"]["mae_mw"] == pytest.approx(750.0)
    assert body["metrics"]["bias_mw"] == pytest.approx(750.0)
    assert body["metrics"]["n"] == 96
    assert body["coverage"]["matched"] == 96
    assert body["coverage"]["status_counts"]["missing_actual"] == 48
    assert body["provenance"]["origin"] == "database"
    assert isinstance(body["daily"], list) and len(body["daily"]) == 3
    assert isinstance(body["series"], list) and body["series"]


def test_overview_respects_the_cutoff_query_parameter(client: TestClient):
    default = client.get("/api/overview").json()["metrics"]["mae_mw"]
    earlier = client.get("/api/overview", params={"cutoff": "10:00"}).json()
    assert earlier["metrics"]["mae_mw"] != default
    assert earlier["cutoff"]["time"] == "10:00"


def test_forecast_endpoint_returns_all_48_intervals(client: TestClient):
    response = client.get("/api/forecasts", params={"date": "2026-01-02"})
    assert response.status_code == 200
    body = response.json()
    assert body["date"] == "2026-01-02"
    assert len(body["intervals"]) == 48
    assert body["metrics"]["n"] == 48
    first = body["intervals"][0]
    assert first["forecast_mw"] == 9500
    assert first["actual_mw"] == 8000
    assert first["error_mw"] == 1500
    assert first["publish_time"].startswith("2026-01-01T11:30")
    assert first["status"] == "matched"
    assert body["selected_publish_times"] == ["2026-01-01T11:30:00+00:00"]
    assert body["cutoff"]["time"] == "12:00"
    assert body["notes"]


def test_forecast_endpoint_marks_missing_values_as_missing(client: TestClient):
    body = client.get("/api/forecasts", params={"date": "2026-01-03"}).json()
    assert len(body["intervals"]) == 48
    assert all(row["actual_mw"] is None for row in body["intervals"])
    assert all(row["status"] == "missing_actual" for row in body["intervals"])
    assert body["coverage"]["matched"] == 0
    assert body["metrics"]["mae_mw"] is None
    assert body["metrics"]["available"] is False


def test_accuracy_endpoint_uses_the_requested_period(client: TestClient):
    response = client.get(
        "/api/accuracy", params={"from": "2026-01-01", "to": "2026-01-02"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["date_from"] == "2026-01-01"
    assert body["date_to"] == "2026-01-02"
    assert len(body["daily"]) == 2
    assert body["metrics"]["n"] == 96
    assert len(body["by_hour"]) == 24
    assert body["error_distribution"]
    assert all("mae_mw" in row for row in body["daily"])


def test_accuracy_daily_endpoint_matches_the_full_accuracy_payload(client: TestClient):
    full = client.get(
        "/api/accuracy", params={"from": "2026-01-01", "to": "2026-01-02"}
    ).json()
    daily = client.get(
        "/api/accuracy/daily", params={"from": "2026-01-01", "to": "2026-01-02"}
    ).json()
    assert daily["daily"] == full["daily"]


def test_invalid_parameters_return_client_errors(client: TestClient):
    assert client.get("/api/accuracy", params={"from": "2026-01-05", "to": "2026-01-06"}).status_code == 400
    assert client.get("/api/accuracy", params={"from": "2026-01-02", "to": "2026-01-01"}).status_code == 400
    assert client.get("/api/forecasts", params={"date": "2026-02-01"}).status_code == 400
    assert client.get("/api/overview", params={"cutoff": "99:00"}).status_code == 400
    assert client.get("/api/overview", params={"cutoff_offset_days": -3}).status_code == 400
    assert client.get("/api/forecasts").status_code == 422  # required `date` missing

    error = client.get("/api/accuracy", params={"from": "2026-01-05"}).json()
    assert error["error"]["code"] == "invalid_parameter"


def test_data_quality_endpoint_reports_counts_and_cutoff(client: TestClient):
    body = client.get("/api/data-quality").json()
    assert body["coverage"]["expected"] == 144
    assert body["interval_reasons"] == {"actual_generation_unavailable_for_interval": 48}
    assert body["late_forecast_excluded_intervals"] == 0
    assert body["distinct_selected_publish_times"] == 3
    assert body["cutoff"]["time"] == "12:00"
    assert body["provenance"]["source_datasets"][0]["name"] == "FUELHH"
    assert body["provenance"]["source_datasets"][1]["name"] == "WINDFOR"


def test_methodology_endpoint_documents_the_rules(client: TestClient):
    body = client.get("/api/methodology").json()
    assert "latest publishTime" in body["selection_rule"]
    assert "error_mw = forecast_mw - actual_mw" in body["error_convention"]
    assert len(body["metrics"]) == 4
    assert body["cutoff"]["day_offset"] == -1


def test_csv_export_contains_the_analytical_dataset(client: TestClient):
    response = client.get(
        "/api/export", params={"from": "2026-01-01", "to": "2026-01-02"}
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    lines = response.text.strip().split("\r\n")
    assert lines[0].startswith("delivery_interval_start_utc")
    assert len(lines) == 97  # header + 96 intervals
    assert "matched" in lines[1]


def test_csv_export_neutralises_formula_injection(client: TestClient):
    from app.export import neutralise

    assert neutralise("=cmd|' /C calc'!A1") == "'=cmd|' /C calc'!A1"
    assert neutralise("@SUM(A1)") == "'@SUM(A1)"
    assert neutralise(-123.5) == "-123.5"  # genuine numbers keep their sign
    assert neutralise(None) == ""


def test_missing_data_returns_an_error_not_fake_metrics(tmp_path):
    """An uninitialised database yields a 503, never synthetic metrics."""
    settings = Settings(
        eval_start=date(2026, 1, 1),
        eval_end=date(2026, 1, 2),
        snapshot_dir=tmp_path / "snap",
        database_url=f"sqlite:///{(tmp_path / 'empty.db').as_posix()}",
        enable_live_fetch=False,
        seed_on_startup=False,
    )
    app = create_app(settings)

    with TestClient(app) as test_client:
        response = test_client.get("/api/overview")
        assert response.status_code == 503
        body = response.json()
        assert body["error"]["code"] == "source_unavailable"
        assert "mae" not in response.text

        health = test_client.get("/api/health")
        assert health.status_code in (200, 503)
        assert health.json()["data"]["status"] in {"unavailable", "degraded"}

        export = test_client.get("/api/export")
        assert export.status_code == 503


def test_database_failure_is_reported_not_hidden(tmp_path):
    """A broken DATABASE_URL degrades the health probe instead of crashing."""
    settings = Settings(
        eval_start=date(2026, 1, 1),
        eval_end=date(2026, 1, 2),
        snapshot_dir=tmp_path / "snap",
        database_url="sqlite:///%2Fnonexistent-root-dir%2Fnope.db",
        seed_on_startup=False,
    )
    app = create_app(settings)
    with TestClient(app) as test_client:
        health = test_client.get("/api/health")
        assert health.status_code in (200, 503)
        payload = health.json()["data"]
        assert payload["database"]["reachable"] is False or payload["status"] in {
            "unavailable",
            "degraded",
        }


def test_refresh_is_disabled_without_an_admin_token(client: TestClient):
    response = client.post("/api/refresh")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "refresh_disabled"


def test_refresh_requires_a_valid_admin_token(tmp_path):
    settings = Settings(
        eval_start=date(2026, 1, 1),
        eval_end=date(2026, 1, 2),
        snapshot_dir=tmp_path / "snap",
        database_url=f"sqlite:///{(tmp_path / 'guarded.db').as_posix()}",
        enable_live_fetch=False,
        seed_on_startup=False,
        admin_token="correct-horse",
    )
    write_snapshot(settings, "fuelhh", actual_rows(days=(1, 2)))
    write_snapshot(settings, "windfor", forecast_rows(days=(1, 2)))
    make_store(settings)

    app = create_app(settings)
    with TestClient(app) as test_client:
        assert test_client.post("/api/refresh").status_code == 401
        assert (
            test_client.post(
                "/api/refresh", headers={"X-Admin-Token": "wrong"}
            ).status_code
            == 401
        )

        ok = test_client.post(
            "/api/refresh",
            params={"source": "snapshot"},
            headers={"X-Admin-Token": "correct-horse"},
        )
        assert ok.status_code == 200
        payload = ok.json()
        assert payload["actual_records"] == 96
        assert [entry["status"] for entry in payload["imports"]] == ["completed", "completed"]
        assert all(entry["coverage_verified"] for entry in payload["imports"])


def test_import_history_is_visible_through_the_api(client: TestClient):
    response = client.get("/api/admin/imports")
    assert response.status_code == 200
    assert isinstance(response.json()["imports"], list)


def test_cors_is_restricted_to_configured_origins(populated_store):
    app = create_app(populated_store.settings)
    with TestClient(app) as test_client:
        allowed = test_client.options(
            "/api/overview",
            headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
        )
        assert allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"
        denied = test_client.options(
            "/api/overview",
            headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
        )
        assert denied.headers.get("access-control-allow-origin") is None
