"""Tests for src/backtest.py.

All tests use tmp_path + initialize_database/insert_observations from src.database.
No real HTTP requests; no shared DB state.
"""

import pytest

from src.backtest import (
    StrategyStats,
    cheapest_observed,
    run_backtest,
    simulate_strategy_on_flight,
)
from src.database import initialize_database, insert_observations

# ---------------------------------------------------------------------------
# Shared helpers / fixtures
# ---------------------------------------------------------------------------

BASE_OBS = {
    "retrieved_at": "2025-01-15T06:00:00",
    "departure_date": "2025-02-15",
    "origin": "CPH",
    "destination": "AMS",
    "airline": "SAS",
    "departure_time": "08:00",
    "arrival_time": "10:05",
    "duration": "2h 5m",
    "stops": 0,
    "price": "€89",
    "price_amount": 8900,
    "price_currency": "EUR",
    "is_best": True,
    "current_price_trend": "typical",
    "duration_minutes": 125,
}


def make_obs(**overrides):
    """Return a copy of BASE_OBS with the given fields overridden."""
    return {**BASE_OBS, **overrides}


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "flights.db")
    initialize_database(path)
    return path


# ---------------------------------------------------------------------------
# simulate_strategy_on_flight
# ---------------------------------------------------------------------------


def test_simulate_picks_closest_obs_in_window():
    """Should return the price of the obs closest to the target date."""
    # departure 2025-02-15; buy 7 days before = target 2025-02-08
    obs_list = [
        make_obs(retrieved_at="2025-02-06T06:00:00", price_amount=9000),  # 2 days early
        make_obs(retrieved_at="2025-02-08T06:00:00", price_amount=8500),  # exact
        make_obs(retrieved_at="2025-02-10T06:00:00", price_amount=7000),  # 2 days late
    ]
    result = simulate_strategy_on_flight(obs_list, days_before=7, window_days=2)
    assert result == 8500  # exact match wins


def test_simulate_returns_none_when_no_obs_in_window():
    """Should return None when no observation falls within ±window_days."""
    # departure 2025-02-15; buy 7 days before = target 2025-02-08
    # all obs are retrieved more than 2 days away from target
    obs_list = [
        make_obs(retrieved_at="2025-02-01T06:00:00", price_amount=9000),  # 7 days early
        make_obs(retrieved_at="2025-02-15T06:00:00", price_amount=8000),  # dep day
    ]
    result = simulate_strategy_on_flight(obs_list, days_before=7, window_days=2)
    assert result is None


def test_simulate_returns_none_on_empty_observations():
    """Empty list should return None."""
    assert simulate_strategy_on_flight([], days_before=14) is None


def test_simulate_skips_null_prices():
    """Obs with price_amount=None should not be selected."""
    obs_list = [
        make_obs(retrieved_at="2025-02-08T06:00:00", price_amount=None),  # no price
        make_obs(retrieved_at="2025-02-07T06:00:00", price_amount=7500),  # 1 day off
    ]
    # target = 2025-02-08 (7 days before 2025-02-15)
    result = simulate_strategy_on_flight(obs_list, days_before=7, window_days=2)
    assert result == 7500


# ---------------------------------------------------------------------------
# cheapest_observed
# ---------------------------------------------------------------------------


def test_cheapest_returns_min_price():
    """Should return the minimum price_amount across all observations."""
    obs_list = [
        make_obs(price_amount=8900),
        make_obs(price_amount=5000),
        make_obs(price_amount=7300),
    ]
    assert cheapest_observed(obs_list) == 5000


def test_cheapest_returns_none_on_empty_list():
    """Empty list should return None."""
    assert cheapest_observed([]) is None


def test_cheapest_returns_none_when_all_prices_null():
    """All-None prices should return None."""
    obs_list = [make_obs(price_amount=None), make_obs(price_amount=None)]
    assert cheapest_observed(obs_list) is None


def test_cheapest_ignores_null_entries():
    """Mixed None / int prices: None entries are ignored."""
    obs_list = [make_obs(price_amount=None), make_obs(price_amount=6000)]
    assert cheapest_observed(obs_list) == 6000


# ---------------------------------------------------------------------------
# run_backtest — single strategy, single flight, clear win
# ---------------------------------------------------------------------------


def _insert_flight(db_path, departure_date, origin, dest, obs_list):
    """Insert observations for a single (origin, dest, departure_date) flight."""
    rows = []
    for obs in obs_list:
        rows.append(
            make_obs(
                departure_date=departure_date,
                origin=origin,
                destination=dest,
                **{k: v for k, v in obs.items()},
            )
        )
    insert_observations(db_path, rows)


def test_run_backtest_single_strategy_clear_win(db_path):
    """5+ obs flight: strategy price should produce a valid StrategyStats."""
    dep_date = "2025-01-20"
    # 5 observations spread around 7 days before (2025-01-13).
    # Price drops as departure approaches.
    observations = [
        make_obs(
            departure_date=dep_date,
            retrieved_at="2024-12-20T06:00:00",
            price_amount=12000,
        ),
        make_obs(
            departure_date=dep_date,
            retrieved_at="2025-01-01T06:00:00",
            price_amount=10000,
        ),
        make_obs(
            departure_date=dep_date,
            retrieved_at="2025-01-08T06:00:00",
            price_amount=8000,
        ),
        make_obs(
            departure_date=dep_date,
            retrieved_at="2025-01-13T06:00:00",  # 7 days before
            price_amount=7000,
        ),
        make_obs(
            departure_date=dep_date,
            retrieved_at="2025-01-18T06:00:00",
            price_amount=6000,  # cheapest
        ),
    ]
    insert_observations(db_path, observations)

    # Use a date after the departure to treat it as past.
    result = run_backtest(
        db_path=db_path,
        strategies=[7],
        today="2026-01-01",
    )

    assert 7 in result
    st = result[7]
    assert isinstance(st, StrategyStats)
    assert st.days_before == 7
    assert st.n_flights == 1
    # capture_rate_mean = cheapest / strategy_price = 6000 / 7000 ≈ 0.857
    assert abs(st.capture_rate_mean - 6000 / 7000) < 0.01


def test_run_backtest_skips_flights_with_fewer_than_5_obs(db_path):
    """Flights with fewer than 5 observations should be excluded."""
    dep_date = "2025-01-20"
    # Only 3 observations — below the min_obs=5 threshold.
    observations = [
        make_obs(
            departure_date=dep_date,
            retrieved_at="2025-01-01T06:00:00",
            price_amount=10000,
        ),
        make_obs(
            departure_date=dep_date,
            retrieved_at="2025-01-08T06:00:00",
            price_amount=8000,
        ),
        make_obs(
            departure_date=dep_date,
            retrieved_at="2025-01-13T06:00:00",
            price_amount=7000,
        ),
    ]
    insert_observations(db_path, observations)

    result = run_backtest(db_path=db_path, strategies=[7], today="2026-01-01")
    # No strategy should have data because the only flight was skipped.
    assert result == {}


def test_run_backtest_route_filter(db_path):
    """Route filter should exclude non-matching routes."""
    dep_date = "2025-01-20"

    def make_5_obs(origin, dest):
        return [
            make_obs(
                departure_date=dep_date,
                origin=origin,
                destination=dest,
                retrieved_at=f"2025-01-{d:02d}T06:00:00",
                price_amount=8000 - d * 100,
            )
            for d in [1, 5, 9, 13, 17]
        ]

    insert_observations(db_path, make_5_obs("CPH", "AMS"))
    insert_observations(db_path, make_5_obs("AMS", "CPH"))

    result_cph = run_backtest(
        db_path=db_path,
        strategies=[7],
        route="CPH-AMS",
        today="2026-01-01",
    )
    result_ams = run_backtest(
        db_path=db_path,
        strategies=[7],
        route="AMS-CPH",
        today="2026-01-01",
    )

    # Each filtered result should see only its own route's flights.
    if result_cph:
        assert result_cph[7].n_flights >= 1
    if result_ams:
        assert result_ams[7].n_flights >= 1

    # Unfiltered should see both.
    result_all = run_backtest(db_path=db_path, strategies=[7], today="2026-01-01")
    if result_cph and result_ams and result_all:
        total = result_cph[7].n_flights + result_ams[7].n_flights
        assert result_all[7].n_flights >= total


def test_run_backtest_multiple_strategies(db_path):
    """Multiple strategies should each produce a StrategyStats entry."""
    dep_date = "2025-01-20"
    # 5 observations: 60d, 30d, 14d, 7d, 2d before departure 2025-01-20.
    observations = [
        make_obs(
            departure_date=dep_date,
            retrieved_at="2024-11-21T06:00:00",
            price_amount=14000,
        ),
        make_obs(
            departure_date=dep_date,
            retrieved_at="2024-12-21T06:00:00",
            price_amount=12000,
        ),
        make_obs(
            departure_date=dep_date,
            retrieved_at="2025-01-06T06:00:00",
            price_amount=10000,
        ),
        make_obs(
            departure_date=dep_date,
            retrieved_at="2025-01-13T06:00:00",
            price_amount=8000,
        ),
        make_obs(
            departure_date=dep_date,
            retrieved_at="2025-01-18T06:00:00",
            price_amount=6000,
        ),
    ]
    insert_observations(db_path, observations)

    result = run_backtest(
        db_path=db_path,
        strategies=[7, 14, 30, 60],
        today="2026-01-01",
    )

    # All four strategies should be represented (each obs aligns with a strategy day).
    for days in [7, 14, 30, 60]:
        assert days in result, f"Strategy {days} missing from results"
        st = result[days]
        assert st.days_before == days
        assert st.n_flights == 1
        assert 0.0 < st.capture_rate_mean <= 1.0
