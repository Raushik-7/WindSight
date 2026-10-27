"""Accuracy metrics.

Definitions (``F`` = selected forecast, ``A`` = actual, ``e = F - A``):

* ``MAE   = mean(|e|)``                       - primary headline metric (MW)
* ``RMSE  = sqrt(mean(e^2))``                 - penalises large errors (MW)
* ``Bias  = mean(e)``                         - positive = overforecast (MW)
* ``MAPE  = mean(|e / A|) * 100``             - only over non-zero actuals

Every metric reports the sample count it was computed from.  An empty sample
returns ``None`` for every metric - never a misleading zero.
"""

from __future__ import annotations

import math
from typing import Iterable, Optional, Sequence

from ..models import MatchedObservation, MetricSet


def _mean(values: Sequence[float]) -> Optional[float]:
    if not values:
        return None
    return sum(values) / len(values)


def _percentile(sorted_values: Sequence[float], fraction: float) -> Optional[float]:
    """Nearest-rank percentile on an already sorted sequence."""
    if not sorted_values:
        return None
    rank = max(1, math.ceil(fraction * len(sorted_values)))
    return sorted_values[min(rank, len(sorted_values)) - 1]


def metrics_from_errors(
    errors: Sequence[float],
    actuals: Sequence[float],
) -> MetricSet:
    """Compute a :class:`MetricSet` from paired error/actual values."""
    if len(errors) != len(actuals):
        raise ValueError("errors and actuals must have the same length")
    if not errors:
        return MetricSet(n=0)

    abs_errors = [abs(e) for e in errors]
    squared = [e * e for e in errors]
    sorted_abs = sorted(abs_errors)

    zero_actual = sum(1 for a in actuals if a == 0)
    mape_pairs = [
        abs(e / a) * 100.0
        for e, a in zip(errors, actuals)
        if a != 0 and math.isfinite(a)
    ]
    excluded_zero = zero_actual

    return MetricSet(
        n=len(errors),
        mae=sum(abs_errors) / len(abs_errors),
        rmse=math.sqrt(sum(squared) / len(squared)),
        bias=sum(errors) / len(errors),
        mape=(sum(mape_pairs) / len(mape_pairs)) if mape_pairs else None,
        mape_n=len(mape_pairs),
        mape_excluded_zero_actual=max(0, excluded_zero),
        median_ae=_percentile(sorted_abs, 0.50),
        p90_ae=_percentile(sorted_abs, 0.90),
        max_ae=max(abs_errors),
        overforecast_n=sum(1 for e in errors if e > 0),
        underforecast_n=sum(1 for e in errors if e < 0),
        exact_n=sum(1 for e in errors if e == 0),
    )


def compute_metrics(observations: Iterable[MatchedObservation]) -> MetricSet:
    """Metrics over the matched observations only."""
    errors: list[float] = []
    actuals: list[float] = []
    for obs in observations:
        if obs.status != "matched":
            continue
        if obs.error_mw is None or obs.actual_mw is None:
            continue
        errors.append(obs.error_mw)
        actuals.append(obs.actual_mw)
    return metrics_from_errors(errors, actuals)


def describe_bias(bias: Optional[float], mae: Optional[float]) -> str:
    """Human-readable bias interpretation - never claims accuracy from a
    near-zero bias alone."""
    if bias is None:
        return "Bias unavailable: no matched observations in this selection."
    if bias > 0:
        direction = "tends to overestimate"
    elif bias < 0:
        direction = "tends to underestimate"
    else:
        direction = "is exactly balanced on average"
    magnitude = f" ({bias:,.1f} MW)"
    caveat = (
        " A near-zero bias does not imply accuracy: positive and negative errors "
        "can cancel while individual errors remain large."
    )
    return f"On average the selected forecast {direction} wind generation{magnitude}.{caveat}"
