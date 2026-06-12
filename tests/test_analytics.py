import pytest

from src.analytics import compute_price_percentile, percentile_rank
from src.database import initialize_database, insert_observations

# ─── percentile_rank (pure function) ─────────────────────────────────────────


def test_percentile_rank_too_few_samples_returns_none():
    """Returns None when len(sorted_prices) < min_samples (default 5)."""
    assert percentile_rank(5000, [1000, 2000, 3000, 4000]) is None


def test_percentile_rank_empty_list_returns_none():
    """Empty input is below min_samples, so None is returned."""
    assert percentile_rank(0, []) is None


def test_percentile_rank_price_below_minimum_returns_zero():
    """Price at or below the first element → 0.0."""
    assert percentile_rank(500, [1000, 2000, 3000, 4000, 5000]) == pytest.approx(0.0)


def test_percentile_rank_price_equal_minimum_returns_zero():
    """Price exactly equal to the minimum → 0.0."""
    assert percentile_rank(1000, [1000, 2000, 3000, 4000, 5000]) == pytest.approx(0.0)


def test_percentile_rank_price_above_maximum_returns_hundred():
    """Price at or above the last element → 100.0."""
    assert percentile_rank(6000, [1000, 2000, 3000, 4000, 5000]) == pytest.approx(100.0)


def test_percentile_rank_price_equal_maximum_returns_hundred():
    """Price exactly equal to the maximum → 100.0."""
    assert percentile_rank(5000, [1000, 2000, 3000, 4000, 5000]) == pytest.approx(100.0)


def test_percentile_rank_price_at_median_of_unique_values():
    """Middle element of 5 unique values → 50.0."""
    # prices: [1000, 2000, 3000, 4000, 5000], index 2 of 4 → 2/4 * 100 = 50.0
    assert percentile_rank(3000, [1000, 2000, 3000, 4000, 5000]) == pytest.approx(50.0)


def test_percentile_rank_price_at_quarter():
    """Second element of 5 → rank 1/4 → 25.0."""
    assert percentile_rank(2000, [1000, 2000, 3000, 4000, 5000]) == pytest.approx(25.0)


def test_percentile_rank_tied_prices_use_midpoint():
    """Tied prices share the midpoint of their index range.

    prices = [1000, 5000, 5000, 5000, 9000]
    5000 appears at indices 1, 2, 3.
    lower_index = bisect_left → 1
    upper_index = bisect_right → 4
    rank = (1 + 4 - 1) / 2 = 2.0
    percentile = 2.0 / 4 * 100 = 50.0
    """
    prices = [1000, 5000, 5000, 5000, 9000]
    assert percentile_rank(5000, prices) == pytest.approx(50.0)


def test_percentile_rank_tied_min_prices_use_midpoint():
    """Multiple occurrences at the minimum fall back to the 0.0 edge case."""
    # price <= prices[0] → 0.0 (edge case fires before bisect)
    prices = [5000, 5000, 6000, 7000, 8000]
    assert percentile_rank(5000, prices) == pytest.approx(0.0)


def test_percentile_rank_min_samples_override():
    """min_samples parameter overrides the default threshold."""
    # With 3 prices and min_samples=3, should return a result (not None)
    result = percentile_rank(2000, [1000, 2000, 3000], min_samples=3)
    assert result == pytest.approx(50.0)


def test_percentile_rank_min_samples_override_none():
    """min_samples=6 with only 5 prices → None."""
    assert percentile_rank(3000, [1000, 2000, 3000, 4000, 5000], min_samples=6) is None


def _obs(price_amount: int, retrieved_at: str) -> dict:
    return {
        "retrieved_at": retrieved_at,
        "departure_date": "2026-06-01",
        "origin": "CPH",
        "destination": "AMS",
        "airline": "SAS",
        "departure_time": "08:00",
        "arrival_time": "09:30",
        "duration": "1h 30m",
        "stops": 0,
        "price": f"€{price_amount // 100}",
        "price_amount": price_amount,
        "price_currency": "EUR",
        "is_best": True,
        "current_price_trend": "low",
        "duration_minutes": 90,
    }


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "flights.db")
    initialize_database(path)
    return path


def test_compute_price_percentile_cheapest_is_near_zero(db_path):
    insert_observations(
        db_path,
        [
            _obs(1000, "2026-01-01T06:00:00+00:00"),
            _obs(2000, "2026-01-02T06:00:00+00:00"),
            _obs(3000, "2026-01-03T06:00:00+00:00"),
            _obs(4000, "2026-01-04T06:00:00+00:00"),
            _obs(5000, "2026-01-05T06:00:00+00:00"),
        ],
    )

    percentile = compute_price_percentile(
        db_path=db_path,
        origin="CPH",
        destination="AMS",
        departure_date="2026-06-01",
        price_amount=1000,
    )

    assert percentile == pytest.approx(0.0)


def test_compute_price_percentile_median_is_near_fifty(db_path):
    insert_observations(
        db_path,
        [
            _obs(1000, "2026-01-01T06:00:00+00:00"),
            _obs(2000, "2026-01-02T06:00:00+00:00"),
            _obs(3000, "2026-01-03T06:00:00+00:00"),
            _obs(4000, "2026-01-04T06:00:00+00:00"),
            _obs(5000, "2026-01-05T06:00:00+00:00"),
        ],
    )

    percentile = compute_price_percentile(
        db_path=db_path,
        origin="CPH",
        destination="AMS",
        departure_date="2026-06-01",
        price_amount=3000,
    )

    assert percentile == pytest.approx(50.0)


def test_compute_price_percentile_returns_none_with_fewer_than_five(db_path):
    insert_observations(
        db_path,
        [
            _obs(1000, "2026-01-01T06:00:00+00:00"),
            _obs(2000, "2026-01-02T06:00:00+00:00"),
            _obs(3000, "2026-01-03T06:00:00+00:00"),
            _obs(4000, "2026-01-04T06:00:00+00:00"),
        ],
    )

    percentile = compute_price_percentile(
        db_path=db_path,
        origin="CPH",
        destination="AMS",
        departure_date="2026-06-01",
        price_amount=3000,
    )

    assert percentile is None


def test_compute_price_percentile_duplicate_max_is_hundred(db_path):
    insert_observations(
        db_path,
        [
            _obs(1000, "2026-01-01T06:00:00+00:00"),
            _obs(2000, "2026-01-02T06:00:00+00:00"),
            _obs(3000, "2026-01-03T06:00:00+00:00"),
            _obs(5000, "2026-01-04T06:00:00+00:00"),
            _obs(5000, "2026-01-05T06:00:00+00:00"),
        ],
    )

    percentile = compute_price_percentile(
        db_path=db_path,
        origin="CPH",
        destination="AMS",
        departure_date="2026-06-01",
        price_amount=5000,
    )

    assert percentile == pytest.approx(100.0)


def test_compute_price_percentile_collapses_same_day_duplicates(db_path):
    """Two observations of the same flight on the same day count as one.

    Without dedup: prices = [1000, 3000, 3000, 5000, 7000, 9000]
    percentile_rank(3000) = midpoint of indices 1..2 = 1.5/5 * 100 = 30.0

    With dedup: prices = [1000, 3000, 5000, 7000, 9000]
    percentile_rank(3000) = rank 1/4 * 100 = 25.0
    """
    insert_observations(
        db_path,
        [
            _obs(1000, "2026-01-01T06:00:00+00:00"),
            _obs(3000, "2026-01-02T06:00:00+00:00"),
            _obs(3000, "2026-01-02T08:00:00+00:00"),  # same-day duplicate
            _obs(5000, "2026-01-03T06:00:00+00:00"),
            _obs(7000, "2026-01-04T06:00:00+00:00"),
            _obs(9000, "2026-01-05T06:00:00+00:00"),
        ],
    )

    percentile = compute_price_percentile(
        db_path=db_path,
        origin="CPH",
        destination="AMS",
        departure_date="2026-06-01",
        price_amount=3000,
    )

    assert percentile == pytest.approx(25.0)
