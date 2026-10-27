"""Elexon client: windowing, retries, malformed responses."""

from __future__ import annotations

from datetime import date, datetime, timezone

import httpx
import pytest

from app.elexon.client import ElexonClient, UpstreamError, date_windows


def make_client(handler) -> ElexonClient:
    transport = httpx.MockTransport(handler)
    return ElexonClient(
        "https://example.test/bmrs/api/v1",
        timeout=5,
        max_retries=3,
        backoff_seconds=0,
        window_days=15,
        transport=transport,
        sleep=lambda _s: None,
    )


def test_date_windows_are_bounded_and_complete():
    windows = date_windows(date(2026, 1, 1), date(2026, 1, 31), 15)
    assert windows == [
        (date(2026, 1, 1), date(2026, 1, 15)),
        (date(2026, 1, 16), date(2026, 1, 30)),
        (date(2026, 1, 31), date(2026, 1, 31)),
    ]
    assert date_windows(date(2026, 1, 5), date(2026, 1, 1), 15) == []


def test_fetch_actuals_splits_requests_and_sends_verified_parameters():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[{"startTime": "2026-01-01T00:00:00Z", "generation": 1}])

    client = make_client(handler)
    rows = client.fetch_actuals(date(2026, 1, 1), date(2026, 1, 31))
    assert len(rows) == 3  # 31 days -> three bounded windows
    assert client.request_count == 3
    first = seen[0]
    assert first.url.path.endswith("/datasets/FUELHH/stream")
    assert first.url.params["settlementDateFrom"] == "2026-01-01"
    assert first.url.params["settlementDateTo"] == "2026-01-15"
    assert first.url.params["fuelType"] == "WIND"


def test_fetch_forecasts_uses_publish_time_filters():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[])

    client = make_client(handler)
    client.fetch_forecasts(
        datetime(2025, 12, 2, tzinfo=timezone.utc),
        datetime(2026, 1, 31, 23, 59, 59, tzinfo=timezone.utc),
    )
    assert seen
    assert seen[0].url.path.endswith("/datasets/WINDFOR/stream")
    assert seen[0].url.params["publishDateTimeFrom"] == "2025-12-02T00:00:00Z"
    assert "settlementDateFrom" not in seen[0].url.params


def test_retries_server_errors_then_succeeds():
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 3:
            return httpx.Response(503, text="busy")
        return httpx.Response(200, json=[{"a": 1}])

    client = make_client(handler)
    rows = client.fetch_actuals(date(2026, 1, 1), date(2026, 1, 1))
    assert rows == [{"a": 1}]
    assert attempts["n"] == 3


def test_gives_up_after_max_retries():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    client = make_client(handler)
    with pytest.raises(UpstreamError):
        client.fetch_actuals(date(2026, 1, 1), date(2026, 1, 1))
    assert client.request_count == 3


def test_non_200_client_error_is_not_retried():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(404, text="not found")

    client = make_client(handler)
    with pytest.raises(UpstreamError):
        client.fetch_actuals(date(2026, 1, 1), date(2026, 1, 1))
    assert calls["n"] == 1


def test_html_response_is_treated_as_an_error_not_as_data():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<!doctype html><html></html>", headers={"content-type": "text/html"})

    client = make_client(handler)
    with pytest.raises(UpstreamError):
        client.fetch_actuals(date(2026, 1, 1), date(2026, 1, 1))


def test_non_list_json_shape_is_rejected():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "object"})

    client = make_client(handler)
    with pytest.raises(UpstreamError):
        client.fetch_actuals(date(2026, 1, 1), date(2026, 1, 1))


def test_malformed_json_body_is_rejected():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json", headers={"content-type": "application/json"})

    client = make_client(handler)
    with pytest.raises(UpstreamError):
        client.fetch_actuals(date(2026, 1, 1), date(2026, 1, 1))
