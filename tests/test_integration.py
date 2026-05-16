"""End-to-end integration test: mocked fast_flights, real DB, real heartbeat file."""

import json
import os
import sys
from datetime import date
from unittest.mock import patch

import fast_flights
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.run_daily import run_collection
from src.database import initialize_database, query_price_history


def _make_result(price="€89"):
    return fast_flights.Result(
        current_price="typical",
        flights=[
            fast_flights.Flight(
                is_best=True,
                name="SAS",
                departure="08:00",
                arrival="10:05",
                arrival_time_ahead="",
                duration="2h 5m",
                stops=0,
                delay=None,
                price=price,
            )
        ],
    )


@pytest.fixture
def ctx(tmp_path):
    db_path = str(tmp_path / "flights.db")
    heartbeat_path = str(tmp_path / "last_run.json")
    initialize_database(db_path)
    return db_path, heartbeat_path


JOBS = [
    ("CPH", "AMS", date(2025, 9, 5)),
    ("AMS", "CPH", date(2025, 9, 6)),
]


def test_observations_are_inserted(ctx):
    db_path, heartbeat_path = ctx
    with patch("fast_flights.get_flights", return_value=_make_result()):
        run_collection(JOBS, db_path, heartbeat_path, sleep_fn=lambda _: None)
    rows = query_price_history(db_path, "2025-09-05")
    assert len(rows) == 1
    assert rows[0]["airline"] == "SAS"
    assert rows[0]["price_amount"] == 8900


def test_heartbeat_is_written(ctx):
    db_path, heartbeat_path = ctx
    with patch("fast_flights.get_flights", return_value=_make_result()):
        run_collection(JOBS, db_path, heartbeat_path, sleep_fn=lambda _: None)
    assert os.path.exists(heartbeat_path)
    with open(heartbeat_path) as f:
        hb = json.load(f)
    assert hb["run_date"] == date.today().isoformat()
    assert hb["total_observations"] == 2
    assert hb["failed_jobs_count"] == 0
    assert hb["total_jobs"] == 2


def test_failed_job_counted_when_result_is_empty(ctx):
    db_path, heartbeat_path = ctx
    empty_result = fast_flights.Result(current_price="typical", flights=[])
    with patch("fast_flights.get_flights", return_value=empty_result):
        run_collection(JOBS, db_path, heartbeat_path, sleep_fn=lambda _: None)
    with open(heartbeat_path) as f:
        hb = json.load(f)
    assert hb["failed_jobs_count"] == 2
    assert hb["total_observations"] == 0


def test_failed_job_counted_when_fetch_raises(ctx):
    db_path, heartbeat_path = ctx
    with patch("fast_flights.get_flights", side_effect=Exception("network error")):
        run_collection(JOBS, db_path, heartbeat_path, sleep_fn=lambda _: None)
    with open(heartbeat_path) as f:
        hb = json.load(f)
    assert hb["failed_jobs_count"] == 2


def test_partial_failure_counted_correctly(ctx):
    db_path, heartbeat_path = ctx
    results = [_make_result(), fast_flights.Result(current_price="typical", flights=[])]
    with patch("fast_flights.get_flights", side_effect=results) as mock_get:
        run_collection(JOBS, db_path, heartbeat_path, sleep_fn=lambda _: None)
    with open(heartbeat_path) as f:
        hb = json.load(f)
    assert hb["total_observations"] == 1
    # The empty-result job is retried once and fails again → still 1 failed
    assert hb["failed_jobs_count"] == 1
    # fetch called 3 times: 2 main pass + 1 retry for the failed job
    assert mock_get.call_count == 3


# --- Retry pass tests ---


def test_retry_pass_recovers_failed_job(ctx):
    """A job that raises in pass 1 but succeeds in pass 2 is counted as success."""
    db_path, heartbeat_path = ctx
    single_job = [("CPH", "AMS", date(2025, 9, 5))]
    results = [Exception("network error"), _make_result()]
    with patch("fast_flights.get_flights", side_effect=results) as mock_get:
        total_obs, failed_count = run_collection(
            single_job, db_path, heartbeat_path, sleep_fn=lambda _: None
        )
    assert failed_count == 0
    assert total_obs == 1
    assert mock_get.call_count == 2


def test_retry_pass_permanent_failure(ctx):
    """A job that fails both passes is counted as failed exactly once."""
    db_path, heartbeat_path = ctx
    single_job = [("CPH", "AMS", date(2025, 9, 5))]
    with patch(
        "fast_flights.get_flights", side_effect=Exception("persistent error")
    ) as mock_get:
        total_obs, failed_count = run_collection(
            single_job, db_path, heartbeat_path, sleep_fn=lambda _: None
        )
    assert failed_count == 1
    assert total_obs == 0
    assert mock_get.call_count == 2


def test_no_retry_when_all_succeed(ctx):
    """When all jobs succeed, fetch is called exactly once per job (no retry pass)."""
    db_path, heartbeat_path = ctx
    with patch("fast_flights.get_flights", return_value=_make_result()) as mock_get:
        run_collection(JOBS, db_path, heartbeat_path, sleep_fn=lambda _: None)
    assert mock_get.call_count == len(JOBS)
