import json
import os
from datetime import date, datetime, timezone

import pytest

from src.database import initialize_database, insert_observations
from src.health_checker import run_health_check


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


def _obs(retrieved_date=None, origin="CPH", destination="AMS", currency="EUR"):
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
        "price_amount": 8900,
        "price_currency": currency,
        "is_best": True,
        "current_price_trend": "typical",
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
    insert_observations(db_path, [_obs()])
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
    past_days = [(date.today() - timedelta(days=i+1)).isoformat() for i in range(7)]
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
    past_days = [(date.today() - timedelta(days=i+1)).isoformat() for i in range(7)]
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
    insert_observations(db_path, [
        _obs(currency="EUR"),
        _obs(currency="USD"),
    ])
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
    _make_heartbeat(heartbeat_path, run_date="2020-01-01", failed_jobs_count=50, total_jobs=100)
    # No observations today → zero obs problem too
    problems = run_health_check(db_path, heartbeat_path=heartbeat_path)
    assert len(problems) >= 2
