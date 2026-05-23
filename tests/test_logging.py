"""Smoke tests for logging consistency across run_collection and setup_logging."""

import logging
import logging.handlers
import os
import sys
from datetime import date
from unittest.mock import patch

import fast_flights
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from scripts.run_daily import run_collection
from src.database import initialize_database
from src.log_config import LOG_DATEFMT, LOG_FORMAT, setup_logging

# --- setup_logging ---


def test_setup_logging_is_callable(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_DIR", str(tmp_path / "logs"))
    setup_logging()  # must not raise


def test_setup_logging_creates_log_dir(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs"
    monkeypatch.setattr(config, "LOG_DIR", str(log_dir))
    setup_logging()
    assert log_dir.is_dir()


def test_setup_logging_attaches_stream_and_file_handlers(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_DIR", str(tmp_path / "logs"))
    setup_logging()
    handlers = logging.getLogger().handlers
    assert any(
        isinstance(h, logging.StreamHandler)
        and not isinstance(h, logging.handlers.TimedRotatingFileHandler)
        for h in handlers
    )
    assert any(
        isinstance(h, logging.handlers.TimedRotatingFileHandler) for h in handlers
    )
    # Close file handler so the tmp_path can be cleaned up cleanly.
    for h in handlers:
        if isinstance(h, logging.handlers.TimedRotatingFileHandler):
            h.close()


def test_setup_logging_uses_midnight_rotation_and_keep_days(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr(config, "LOG_KEEP_DAYS", 14)
    with patch("logging.handlers.TimedRotatingFileHandler") as mock_handler:
        # The mocked handler instance must satisfy basicConfig's handler interface.
        instance = mock_handler.return_value
        instance.level = logging.NOTSET
        setup_logging()
    assert mock_handler.called
    kwargs = mock_handler.call_args.kwargs
    assert kwargs["when"] == "midnight"
    assert kwargs["backupCount"] == config.LOG_KEEP_DAYS
    assert kwargs["filename"] == os.path.join(config.LOG_DIR, "tracker.log")


def test_log_format_contains_required_fields():
    assert "%(asctime)s" in LOG_FORMAT
    assert "%(levelname)" in LOG_FORMAT
    assert "%(name)s" in LOG_FORMAT
    assert "%(message)s" in LOG_FORMAT


def test_log_datefmt_is_readable():
    # Should be a human-readable date, not an epoch timestamp.
    assert "%Y" in LOG_DATEFMT
    assert "%H" in LOG_DATEFMT


# --- run_collection log output ---


@pytest.fixture
def ctx(tmp_path):
    db_path = str(tmp_path / "flights.db")
    heartbeat_path = str(tmp_path / "last_run.json")
    initialize_database(db_path)
    return db_path, heartbeat_path


JOBS = [("CPH", "AMS", date(2025, 9, 5))]


def _make_result():
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
                price="€89",
            )
        ],
    )


def test_progress_logged_at_info(ctx, caplog):
    db_path, heartbeat_path = ctx
    with patch("fast_flights.get_flights", return_value=_make_result()):
        with caplog.at_level(logging.INFO):
            run_collection(JOBS, db_path, heartbeat_path, sleep_fn=lambda _: None)
    messages = caplog.text
    assert "CPH" in messages
    assert "AMS" in messages
    assert "[1/1]" in messages


def test_stored_count_logged(ctx, caplog):
    db_path, heartbeat_path = ctx
    with patch("fast_flights.get_flights", return_value=_make_result()):
        with caplog.at_level(logging.INFO):
            run_collection(JOBS, db_path, heartbeat_path, sleep_fn=lambda _: None)
    assert "Stored 1 flight" in caplog.text


def test_summary_logged_with_counts(ctx, caplog):
    db_path, heartbeat_path = ctx
    with patch("fast_flights.get_flights", return_value=_make_result()):
        with caplog.at_level(logging.INFO):
            run_collection(JOBS, db_path, heartbeat_path, sleep_fn=lambda _: None)
    assert "Total observations: 1" in caplog.text
    assert "Failed jobs: 0" in caplog.text


def test_failure_logged_at_error_with_context(ctx, caplog):
    db_path, heartbeat_path = ctx
    with patch("fast_flights.get_flights", side_effect=Exception("timeout error")):
        with caplog.at_level(logging.ERROR):
            run_collection(JOBS, db_path, heartbeat_path, sleep_fn=lambda _: None)
    assert "timeout error" in caplog.text
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) >= 1
    # Error must include route context
    error_text = " ".join(r.message for r in errors)
    assert "CPH" in error_text or "AMS" in error_text


def test_failure_warning_includes_reason(ctx, caplog):
    db_path, heartbeat_path = ctx
    with patch("fast_flights.get_flights", side_effect=Exception("timeout error")):
        with caplog.at_level(logging.WARNING):
            run_collection(JOBS, db_path, heartbeat_path, sleep_fn=lambda _: None)
    warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    failed_lines = [line for line in warnings if line.startswith("Failed:")]
    assert failed_lines
    assert "timeout error" in failed_lines[0]
