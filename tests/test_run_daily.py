"""Unit tests for two-pass retry behavior in run_collection()."""

import json
import os
import sys
from datetime import date
from unittest.mock import patch

import fast_flights
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.run_daily import run_collection
from src.database import initialize_database


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


JOBS = [("CPH", "AMS", date(2025, 9, 5))]


@pytest.fixture
def ctx(tmp_path):
    db_path = str(tmp_path / "flights.db")
    heartbeat_path = str(tmp_path / "last_run.json")
    initialize_database(db_path)
    return db_path, heartbeat_path


# --- All succeed on first pass — no retry triggered ---

def test_no_retries_when_all_succeed(ctx):
    """When all jobs succeed on first pass, fetch is called exactly once per job."""
    db_path, heartbeat_path = ctx
    with patch("fast_flights.get_flights", return_value=_make_result()) as mock_get:
        run_collection(JOBS, db_path, heartbeat_path, sleep_fn=lambda _: None)
    assert mock_get.call_count == 1
    with open(heartbeat_path) as f:
        hb = json.load(f)
    assert hb["failed_jobs_count"] == 0


# --- Fail first pass, recover on retry ---

def test_retry_recovers_failed_job(ctx):
    """Job fails pass 1 but succeeds on pass 2 — counted as success."""
    db_path, heartbeat_path = ctx
    with patch(
        "fast_flights.get_flights",
        side_effect=[Exception("timeout"), _make_result()],
    ):
        run_collection(JOBS, db_path, heartbeat_path, sleep_fn=lambda _: None)
    with open(heartbeat_path) as f:
        hb = json.load(f)
    assert hb["failed_jobs_count"] == 0
    assert hb["total_observations"] == 1


# --- Fail both passes — counted as single failure ---

def test_job_fails_both_passes(ctx):
    """Job fails pass 1 and pass 2 — counted as exactly 1 failed job."""
    db_path, heartbeat_path = ctx
    with patch("fast_flights.get_flights", side_effect=Exception("fail")):
        run_collection(JOBS, db_path, heartbeat_path, sleep_fn=lambda _: None)
    with open(heartbeat_path) as f:
        hb = json.load(f)
    assert hb["failed_jobs_count"] == 1


# --- Empty result retried and recovers ---

def test_empty_result_recovered_on_retry(ctx):
    """Zero-flight result on pass 1, real flights on pass 2 — success."""
    db_path, heartbeat_path = ctx
    empty = fast_flights.Result(current_price="typical", flights=[])
    with patch(
        "fast_flights.get_flights",
        side_effect=[empty, _make_result()],
    ):
        run_collection(JOBS, db_path, heartbeat_path, sleep_fn=lambda _: None)
    with open(heartbeat_path) as f:
        hb = json.load(f)
    assert hb["failed_jobs_count"] == 0
    assert hb["total_observations"] == 1


# --- Empty result stays empty on retry ---

def test_empty_result_stays_failed_on_retry(ctx):
    """Zero-flight result on both passes — counted as failed."""
    db_path, heartbeat_path = ctx
    empty = fast_flights.Result(current_price="typical", flights=[])
    with patch("fast_flights.get_flights", return_value=empty):
        run_collection(JOBS, db_path, heartbeat_path, sleep_fn=lambda _: None)
    with open(heartbeat_path) as f:
        hb = json.load(f)
    assert hb["failed_jobs_count"] == 1


# --- Multiple jobs: partial recovery ---

def test_partial_recovery(ctx):
    """Two jobs: one recovers on retry, one stays failed."""
    db_path, heartbeat_path = ctx
    jobs = [
        ("CPH", "AMS", date(2025, 9, 5)),
        ("AMS", "CPH", date(2025, 9, 6)),
    ]
    # Pass 1: both fail. Pass 2: job 1 succeeds, job 2 fails.
    with patch(
        "fast_flights.get_flights",
        side_effect=[
            Exception("fail"),   # job 1 pass 1
            Exception("fail"),   # job 2 pass 1
            _make_result(),      # job 1 pass 2
            Exception("fail"),   # job 2 pass 2
        ],
    ):
        run_collection(jobs, db_path, heartbeat_path, sleep_fn=lambda _: None)
    with open(heartbeat_path) as f:
        hb = json.load(f)
    assert hb["failed_jobs_count"] == 1
    assert hb["total_observations"] == 1


# --- Retry delay is applied ---

def test_retry_delay_is_applied(ctx):
    """sleep_fn is called with FETCH_RETRY_DELAY_SECONDS for each retried job."""
    db_path, heartbeat_path = ctx
    sleep_calls = []
    with patch("config.FETCH_RETRY_DELAY_SECONDS", 30):
        with patch("fast_flights.get_flights", side_effect=Exception("fail")):
            run_collection(JOBS, db_path, heartbeat_path, sleep_fn=lambda s: sleep_calls.append(s))
    assert 30 in sleep_calls


# --- Max 2 attempts per job ---

def test_max_two_attempts_per_job(ctx):
    """Each job is fetched at most twice (pass 1 + pass 2)."""
    db_path, heartbeat_path = ctx
    with patch("fast_flights.get_flights", side_effect=Exception("fail")) as mock_get:
        run_collection(JOBS, db_path, heartbeat_path, sleep_fn=lambda _: None)
    assert mock_get.call_count == 2
