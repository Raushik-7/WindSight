"""Metric calculations against hand-computed examples."""

from __future__ import annotations

import math

import pytest

from app.analysis.metrics import compute_metrics, describe_bias, metrics_from_errors
from app.models import MatchedObservation


def obs(forecast, actual):
    """Build a matched observation directly (fixtures, not real data)."""
    from datetime import datetime, timezone

    error = forecast - actual
    return MatchedObservation(
        start_time=datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc),
        delivery_date="2026-01-01",
        decision_cutoff=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        status="matched",
        forecast_mw=forecast,
        actual_mw=actual,
        error_mw=error,
        absolute_error_mw=abs(error),
        squared_error_mw2=error * error,
    )


def test_mae_rmse_bias_from_a_hand_calculated_sample():
    # errors: +10, -4, +2  ->  MAE = 16/3, bias = 8/3
    result = metrics_from_errors([10.0, -4.0, 2.0], [100.0, 100.0, 100.0])
    assert result.n == 3
    assert result.mae == pytest.approx(16 / 3)
    assert result.bias == pytest.approx(8 / 3)
    assert result.rmse == pytest.approx(math.sqrt((100 + 16 + 4) / 3))
    assert result.overforecast_n == 2
    assert result.underforecast_n == 1
    assert result.exact_n == 0


def test_positive_bias_means_overforecast():
    result = metrics_from_errors([+500.0, +700.0], [10000.0, 10000.0])
    assert result.bias == pytest.approx(600.0)
    assert "overestimate" in describe_bias(result.bias, result.mae)


def test_negative_bias_means_underforecast():
    result = metrics_from_errors([-500.0, -700.0], [10000.0, 10000.0])
    assert result.bias == pytest.approx(-600.0)
    assert "underestimate" in describe_bias(result.bias, result.mae)


def test_mape_skips_zero_actuals_and_reports_the_exclusion():
    # 50/1000 = 5%, 0/0 excluded, 100/100 = 100%  ->  MAPE = 52.5%
    result = metrics_from_errors([50.0, 10.0, 100.0], [1000.0, 0.0, 100.0])
    assert result.mape == pytest.approx(52.5)
    assert result.mape_n == 2
    assert result.mape_excluded_zero_actual == 1


def test_all_zero_actuals_leave_mape_unavailable_not_zero():
    result = metrics_from_errors([10.0, -10.0], [0.0, 0.0])
    assert result.mape is None
    assert result.mape_n == 0
    assert result.mape_excluded_zero_actual == 2


def test_empty_dataset_returns_unavailable_metrics():
    result = metrics_from_errors([], [])
    assert result.n == 0
    assert result.available is False
    assert result.mae is None
    assert result.rmse is None
    assert result.bias is None
    assert result.mape is None
    assert result.max_ae is None


def test_median_and_percentile_and_max():
    result = metrics_from_errors([1.0, 2.0, 3.0, 4.0, 100.0], [10.0] * 5)
    assert result.median_ae == 3.0
    assert result.p90_ae == 100.0
    assert result.max_ae == 100.0


def test_mismatched_lengths_are_rejected():
    with pytest.raises(ValueError):
        metrics_from_errors([1.0], [1.0, 2.0])


def test_compute_metrics_only_uses_matched_observations():
    from datetime import datetime, timezone
    from app.models import MatchedObservation

    matched = obs(1100.0, 1000.0)
    unmatched = MatchedObservation(
        start_time=datetime(2026, 1, 1, 11, 0, tzinfo=timezone.utc),
        delivery_date="2026-01-01",
        decision_cutoff=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        status="missing_actual",
        forecast_mw=5000.0,
        actual_mw=None,
    )
    result = compute_metrics([matched, unmatched])
    assert result.n == 1
    assert result.mae == pytest.approx(100.0)


def test_describe_bias_never_claims_accuracy_from_zero_bias():
    text = describe_bias(0.0, 1500.0)
    assert "cancel" in text
    assert "balanced" in text
