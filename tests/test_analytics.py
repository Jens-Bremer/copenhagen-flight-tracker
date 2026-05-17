import pytest

from src.analytics import compute_price_percentile
from src.database import initialize_database, insert_observations


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
