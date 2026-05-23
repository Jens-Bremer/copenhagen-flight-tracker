import os
import sys
from datetime import date
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.collection import execute_single_job


def test_execute_single_job_success(tmp_path):
    """Returns (N, None) when fetch, parse, and insert all succeed."""
    db = str(tmp_path / "flights.db")
    with (
        patch(
            "scripts.collection.fetch_flights_for_date",
            return_value=MagicMock(),
        ),
        patch("scripts.collection.parse_flights", return_value=[{"x": 1}]),
        patch("scripts.collection.insert_observations", return_value=3),
    ):
        inserted, exc = execute_single_job("CPH", "AMS", date(2026, 6, 1), db)
    assert inserted == 3
    assert exc is None


def test_execute_single_job_fetch_raises(tmp_path):
    """Returns (0, exc) when fetch raises — never re-raises."""
    db = str(tmp_path / "flights.db")
    boom = RuntimeError("timeout")
    with patch("scripts.collection.fetch_flights_for_date", side_effect=boom):
        inserted, exc = execute_single_job("CPH", "AMS", date(2026, 6, 1), db)
    assert inserted == 0
    assert exc is boom


def test_execute_single_job_insert_raises(tmp_path):
    """Returns (0, exc) when insert raises."""
    db = str(tmp_path / "flights.db")
    boom = OSError("disk full")
    with (
        patch(
            "scripts.collection.fetch_flights_for_date",
            return_value=MagicMock(),
        ),
        patch("scripts.collection.parse_flights", return_value=[{"x": 1}]),
        patch("scripts.collection.insert_observations", side_effect=boom),
    ):
        inserted, exc = execute_single_job("CPH", "AMS", date(2026, 6, 1), db)
    assert inserted == 0
    assert exc is boom


def test_execute_single_job_zero_rows_no_exception(tmp_path):
    """Returns (0, None) when insert returns 0 — valid empty result."""
    db = str(tmp_path / "flights.db")
    with (
        patch(
            "scripts.collection.fetch_flights_for_date",
            return_value=MagicMock(),
        ),
        patch("scripts.collection.parse_flights", return_value=[]),
        patch("scripts.collection.insert_observations", return_value=0),
    ):
        inserted, exc = execute_single_job("CPH", "AMS", date(2026, 6, 1), db)
    assert inserted == 0
    assert exc is None


def test_execute_single_job_passes_raise_on_failure_true(tmp_path):
    """fetch_flights_for_date must be called with raise_on_failure=True."""
    db = str(tmp_path / "flights.db")
    with (
        patch(
            "scripts.collection.fetch_flights_for_date",
            return_value=MagicMock(),
        ) as mock_fetch,
        patch("scripts.collection.parse_flights", return_value=[]),
        patch("scripts.collection.insert_observations", return_value=0),
    ):
        execute_single_job("CPH", "AMS", date(2026, 6, 1), db)
    _args, kwargs = mock_fetch.call_args
    assert kwargs.get("raise_on_failure") is True
