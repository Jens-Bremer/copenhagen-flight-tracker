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
    with patch("fast_flights.get_flights", side_effect=results):
        run_collection(JOBS, db_path, heartbeat_path, sleep_fn=lambda _: None)
    with open(heartbeat_path) as f:
        hb = json.load(f)
    assert hb["total_observations"] == 1
    assert hb["failed_jobs_count"] == 1


def test_retry_recovers_transient_failure(ctx):
    """A job that fails on pass 1 but succeeds on pass 2 stores data correctly."""
    db_path, heartbeat_path = ctx
    with patch(
        "fast_flights.get_flights",
        side_effect=[Exception("timeout"), _make_result(), _make_result()],
    ):
        run_collection(JOBS, db_path, heartbeat_path, sleep_fn=lambda _: None)
    rows = query_price_history(db_path, "2025-09-05")
    assert len(rows) == 1
    assert rows[0]["airline"] == "SAS"
