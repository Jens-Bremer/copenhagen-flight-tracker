import json
import os
from datetime import date

import pytest

import config
from src.database import initialize_database, insert_observations
from src.health_checker import (
    check_missing_routes,
    check_observation_count,
    check_price_variance,
    run_health_check,
)

TODAY = date.today().isoformat()


def _make_heartbeat(path, run_date=None, failed_jobs_count=0, total_jobs=100):
    data = {
        "run_date": run_date or TODAY,
        "total_observations": 100,
        "failed_jobs_count": failed_jobs_count,
        "total_jobs": total_jobs,
        "duration_seconds": 3600.0,
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f)


def _obs(
    retrieved_date=None,
    origin="CPH",
    destination="AMS",
    currency="EUR",
    price_amount=8900,
):
    ts = f"{retrieved_date or TODAY}T06:00:00+00:00"
    return {
        "retrieved_at": ts,
        "departure_date": "2025-09-19",
        "origin": origin,
        "destination": destination,
        "airline": "SAS",
        "departure_time": "08:00",
        "arrival_time": "10:05",
        "duration": "2h 5m",
        "stops": 0,
        "price": "€89",
        "price_amount": price_amount,
        "price_currency": currency,
        "is_best": True,
        "current_price_trend": "typical",
        "duration_minutes": 125,
    }


@pytest.fixture
def ctx(tmp_path):
    db_path = str(tmp_path / "flights.db")
    heartbeat_path = str(tmp_path / "last_run.json")
    initialize_database(db_path)
    return db_path, heartbeat_path


# --- Heartbeat checks ---


def test_no_problems_when_all_healthy(ctx):
    db_path, heartbeat_path = ctx
    _make_heartbeat(heartbeat_path)
    obs = []
    for origin, dest in config.ROUTES:
        for price in [4500, 5500, 6500, 7500]:
            obs.append(_obs(origin=origin, destination=dest, price_amount=price))
    insert_observations(db_path, obs)
    problems = run_health_check(db_path, heartbeat_path=heartbeat_path)
    assert problems == []


def test_problem_when_heartbeat_missing(ctx):
    db_path, heartbeat_path = ctx
    insert_observations(db_path, [_obs()])
    problems = run_health_check(db_path, heartbeat_path=heartbeat_path)
    assert any("heartbeat" in p.lower() or "stale" in p.lower() for p in problems)


def test_problem_when_heartbeat_run_date_is_not_today(ctx):
    db_path, heartbeat_path = ctx
    _make_heartbeat(heartbeat_path, run_date="2020-01-01")
    insert_observations(db_path, [_obs()])
    problems = run_health_check(db_path, heartbeat_path=heartbeat_path)
    assert any("heartbeat" in p.lower() or "stale" in p.lower() for p in problems)


# --- Failure rate ---


def test_problem_when_failure_rate_exceeds_25_percent(ctx):
    db_path, heartbeat_path = ctx
    _make_heartbeat(heartbeat_path, failed_jobs_count=30, total_jobs=100)
    insert_observations(db_path, [_obs()])
    problems = run_health_check(db_path, heartbeat_path=heartbeat_path)
    assert any("fail" in p.lower() for p in problems)


def test_no_problem_when_failure_rate_at_25_percent(ctx):
    db_path, heartbeat_path = ctx
    _make_heartbeat(heartbeat_path, failed_jobs_count=25, total_jobs=100)
    insert_observations(db_path, [_obs()])
    problems = run_health_check(db_path, heartbeat_path=heartbeat_path)
    assert not any("fail" in p.lower() for p in problems)


# --- Zero observations today ---


def test_problem_when_no_observations_today(ctx):
    db_path, heartbeat_path = ctx
    _make_heartbeat(heartbeat_path)
    # Insert observation with a past retrieved_at — not today
    problems = run_health_check(db_path, heartbeat_path=heartbeat_path)
    assert any("observation" in p.lower() or "zero" in p.lower() for p in problems)


# --- Observation count drop ---


def test_problem_when_today_count_below_50_percent_of_average(ctx):
    db_path, heartbeat_path = ctx
    _make_heartbeat(heartbeat_path)
    # Insert 100 obs each day for the past 7 days
    from datetime import timedelta

    past_days = [(date.today() - timedelta(days=i + 1)).isoformat() for i in range(7)]
    historical = [_obs(retrieved_date=d) for d in past_days for _ in range(100)]
    insert_observations(db_path, historical)
    # Today: only 10 obs (well below 50% of 100 average)
    insert_observations(db_path, [_obs() for _ in range(10)])
    problems = run_health_check(db_path, heartbeat_path=heartbeat_path)
    assert any("drop" in p.lower() or "count" in p.lower() for p in problems)


def test_no_problem_when_today_count_above_50_percent_of_average(ctx):
    db_path, heartbeat_path = ctx
    _make_heartbeat(heartbeat_path)
    from datetime import timedelta

    past_days = [(date.today() - timedelta(days=i + 1)).isoformat() for i in range(7)]
    historical = [_obs(retrieved_date=d) for d in past_days for _ in range(100)]
    insert_observations(db_path, historical)
    # Today: 60 obs (above 50% of 100)
    insert_observations(db_path, [_obs() for _ in range(60)])
    problems = run_health_check(db_path, heartbeat_path=heartbeat_path)
    assert not any("drop" in p.lower() or "count" in p.lower() for p in problems)


# --- Currency inconsistency ---


def test_problem_when_multiple_currencies_today(ctx):
    db_path, heartbeat_path = ctx
    _make_heartbeat(heartbeat_path)
    insert_observations(
        db_path,
        [
            _obs(currency="EUR"),
            _obs(currency="USD"),
        ],
    )
    problems = run_health_check(db_path, heartbeat_path=heartbeat_path)
    assert any("currenc" in p.lower() for p in problems)


def test_no_problem_with_single_currency_today(ctx):
    db_path, heartbeat_path = ctx
    _make_heartbeat(heartbeat_path)
    insert_observations(db_path, [_obs(currency="EUR"), _obs(currency="EUR")])
    problems = run_health_check(db_path, heartbeat_path=heartbeat_path)
    assert not any("currenc" in p.lower() for p in problems)


# --- Multiple problems ---


def test_returns_multiple_problems(ctx):
    db_path, heartbeat_path = ctx
    _make_heartbeat(
        heartbeat_path, run_date="2020-01-01", failed_jobs_count=50, total_jobs=100
    )
    # No observations today → zero obs problem too
    problems = run_health_check(db_path, heartbeat_path=heartbeat_path)
    assert len(problems) >= 2


# --- check_missing_routes ---


def test_check_missing_routes_flags_missing_route(ctx):
    db_path, _ = ctx
    insert_observations(db_path, [_obs(origin="CPH", destination="AMS")])
    problems = check_missing_routes(db_path, TODAY, [("CPH", "AMS"), ("AMS", "CPH")])
    assert len(problems) == 1
    assert "Missing route" in problems[0]


def test_check_missing_routes_empty_when_all_routes_present(ctx):
    db_path, _ = ctx
    insert_observations(
        db_path,
        [_obs(origin="CPH", destination="AMS"), _obs(origin="AMS", destination="CPH")],
    )
    problems = check_missing_routes(db_path, TODAY, [("CPH", "AMS"), ("AMS", "CPH")])
    assert problems == []


def test_check_missing_routes_empty_on_empty_db(ctx):
    db_path, _ = ctx
    problems = check_missing_routes(db_path, TODAY, [("CPH", "AMS"), ("AMS", "CPH")])
    assert problems == []


# --- check_price_variance ---


def test_check_price_variance_flags_uniform_prices(ctx):
    db_path, _ = ctx
    insert_observations(db_path, [_obs(price_amount=5000) for _ in range(10)])
    problems = check_price_variance(db_path, TODAY)
    assert len(problems) == 1
    assert "Price variance" in problems[0]


def test_check_price_variance_no_problem_with_varied_prices(ctx):
    db_path, _ = ctx
    prices = [4500, 5000, 5500, 6000, 6500, 7000, 7500, 8000, 8500, 9000]
    insert_observations(db_path, [_obs(price_amount=p) for p in prices])
    problems = check_price_variance(db_path, TODAY)
    assert problems == []


def test_check_price_variance_empty_on_empty_db(ctx):
    db_path, _ = ctx
    problems = check_price_variance(db_path, TODAY)
    assert problems == []


# --- check_observation_count ---


def test_check_observation_count_flags_below_minimum(ctx):
    db_path, _ = ctx
    insert_observations(db_path, [_obs() for _ in range(10)])
    problems = check_observation_count(db_path, TODAY, expected_min=50)
    assert len(problems) == 1
    assert "Low observation count" in problems[0]


def test_check_observation_count_no_problem_at_minimum(ctx):
    db_path, _ = ctx
    insert_observations(db_path, [_obs() for _ in range(50)])
    problems = check_observation_count(db_path, TODAY, expected_min=50)
    assert problems == []


def test_check_observation_count_empty_on_empty_db(ctx):
    db_path, _ = ctx
    problems = check_observation_count(db_path, TODAY, expected_min=50)
    assert problems == []


# --- run_health_check integration: new checks ---


def test_run_health_check_surfaces_missing_route_and_price_variance(ctx):
    db_path, heartbeat_path = ctx
    _make_heartbeat(heartbeat_path)
    # Only CPH→AMS with uniform price — AMS→CPH is missing, CPH→AMS has no variance
    insert_observations(
        db_path,
        [_obs(origin="CPH", destination="AMS", price_amount=5000) for _ in range(5)],
    )
    problems = run_health_check(db_path, heartbeat_path=heartbeat_path, run_date=TODAY)
    assert any("Missing route" in p for p in problems)
    assert any("Price variance" in p for p in problems)
