"""Guarded statistical primitives shared by the insight builders.

All functions are pure and stdlib-only.
"""

from __future__ import annotations

import statistics
from typing import Optional, Sequence

from src.analytics import percentile_rank


def coefficient_of_variation(values: Sequence[float]) -> Optional[float]:
    """Return stdev / mean, or None when undefined.

    - n < 2  -> 0.0 (no spread observed)
    - mean == 0 -> None (CV undefined)
    - otherwise stdev(values) / mean(values), non-negative.
    """
    n = len(values)
    if n < 2:
        return 0.0
    mean = statistics.fmean(values)
    if mean == 0:
        return None
    sd = statistics.stdev(values)
    return sd / mean


def bucketed_percentile(
    value: float, reference_values: Sequence[float], min_samples: int = 3
) -> Optional[float]:
    """Percentile rank of `value` within `reference_values` (0..100).

    Thin wrapper over `src.analytics.percentile_rank` with `min_samples`
    lowered to the insights' n>=3 convention by default. Returns None
    when the reference is too small to be meaningful.
    """
    if not reference_values:
        return None
    ref_sorted = sorted(reference_values)
    return percentile_rank(int(round(value)), ref_sorted, min_samples=min_samples)


def trailing_median(values: Sequence[float]) -> Optional[float]:
    """Median of values, or None when empty."""
    if not values:
        return None
    return float(statistics.median(values))


def linear_trend_slope(points: Sequence[tuple[float, float]]) -> Optional[float]:
    """Least-squares slope of (x, y) points.

    Returns None at n < 2 or when all xs are equal (vertical fit).
    """
    n = len(points)
    if n < 2:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den = sum((x - mean_x) ** 2 for x in xs)
    if den == 0:
        return None
    return num / den
