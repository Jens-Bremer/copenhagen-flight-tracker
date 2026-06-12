import pytest

from src.insights.stats import (
    bucketed_percentile,
    coefficient_of_variation,
    linear_trend_slope,
    trailing_median,
)


# ─── coefficient_of_variation ────────────────────────────────────────────────


def test_cv_constant_series_is_zero():
    assert coefficient_of_variation([5, 5, 5]) == pytest.approx(0.0)


def test_cv_mean_zero_returns_none():
    assert coefficient_of_variation([0, 0, 0]) is None


def test_cv_single_value_is_zero():
    # n<2 -> 0.0 (no observed spread)
    assert coefficient_of_variation([100]) == pytest.approx(0.0)


def test_cv_empty_is_zero():
    assert coefficient_of_variation([]) == pytest.approx(0.0)


def test_cv_known_spread_positive():
    cv = coefficient_of_variation([100, 200, 300, 400, 500])
    assert cv is not None and cv > 0


# ─── bucketed_percentile ─────────────────────────────────────────────────────


def test_bucketed_percentile_known_value():
    # 300 is the middle of [100,200,300,400,500] -> 50th
    assert bucketed_percentile(300, [100, 200, 300, 400, 500]) == pytest.approx(50.0)


def test_bucketed_percentile_min_samples_default_3():
    # n=2 < 3 -> None
    assert bucketed_percentile(150, [100, 200]) is None


def test_bucketed_percentile_n3_allowed():
    # n=3 meets the lowered min_samples
    assert bucketed_percentile(200, [100, 200, 300]) == pytest.approx(50.0)


def test_bucketed_percentile_empty():
    assert bucketed_percentile(100, []) is None


# ─── trailing_median ─────────────────────────────────────────────────────────


def test_trailing_median_basic():
    assert trailing_median([1, 2, 3, 4, 5]) == pytest.approx(3.0)


def test_trailing_median_empty_is_none():
    assert trailing_median([]) is None


# ─── linear_trend_slope ──────────────────────────────────────────────────────


def test_slope_rising_line():
    # y = 2x → slope 2.0
    pts = [(0, 0.0), (1, 2.0), (2, 4.0), (3, 6.0)]
    assert linear_trend_slope(pts) == pytest.approx(2.0)


def test_slope_falling_line():
    pts = [(0, 10.0), (1, 8.0), (2, 6.0), (3, 4.0)]
    assert linear_trend_slope(pts) == pytest.approx(-2.0)


def test_slope_flat_line():
    pts = [(0, 5.0), (1, 5.0), (2, 5.0)]
    assert linear_trend_slope(pts) == pytest.approx(0.0)


def test_slope_single_point_returns_none():
    assert linear_trend_slope([(0, 1.0)]) is None


def test_slope_all_same_x_returns_none():
    assert linear_trend_slope([(1, 1.0), (1, 2.0), (1, 3.0)]) is None
