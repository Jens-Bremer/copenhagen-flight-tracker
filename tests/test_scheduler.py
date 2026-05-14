"""Tests for run_scheduler: job registration and callable job functions."""
import os
import sys
from unittest.mock import MagicMock, patch

import schedule
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from scripts.run_scheduler import setup_schedule, _daily_job, _health_check_job


@pytest.fixture(autouse=True)
def clear_schedule():
    """Ensure each test starts with a clean schedule."""
    schedule.clear()
    yield
    schedule.clear()


# --- Job registration ---

def test_setup_schedule_registers_two_jobs():
    setup_schedule()
    assert len(schedule.jobs) == 2


def test_daily_job_scheduled_at_window_start():
    setup_schedule()
    expected_time = f"{config.DAILY_WINDOW_START_HOUR:02d}:00"
    times = [str(job.next_run.strftime("%H:%M")) for job in schedule.jobs]
    assert expected_time in times


def test_health_check_scheduled_at_2330():
    setup_schedule()
    times = [str(job.next_run.strftime("%H:%M")) for job in schedule.jobs]
    assert "23:30" in times


def test_jobs_run_daily():
    setup_schedule()
    for job in schedule.jobs:
        assert job.interval == 1
        assert str(job.unit) == "days"


# --- Job functions ---

def test_daily_job_calls_run_collection(tmp_path):
    db_path = str(tmp_path / "flights.db")
    heartbeat_path = str(tmp_path / "last_run.json")
    with patch("scripts.run_scheduler.run_collection") as mock_run, \
         patch("scripts.run_scheduler.generate_target_dates", return_value=[]), \
         patch("scripts.run_scheduler.expand_jobs", return_value=[]), \
         patch("scripts.run_scheduler.compute_sleep_intervals", return_value=[]), \
         patch("scripts.run_scheduler.config") as mock_cfg:
        mock_cfg.ROUTES = config.ROUTES
        mock_cfg.DATABASE_PATH = db_path
        mock_cfg.DAILY_WINDOW_START_HOUR = config.DAILY_WINDOW_START_HOUR
        mock_cfg.DAILY_WINDOW_END_HOUR = config.DAILY_WINDOW_END_HOUR
        _daily_job(heartbeat_path=heartbeat_path)
    mock_run.assert_called_once()


def test_health_check_job_calls_run_health_check(tmp_path):
    db_path = str(tmp_path / "flights.db")
    with patch("scripts.run_scheduler.run_health_check", return_value=[]) as mock_hc, \
         patch("scripts.run_scheduler.config") as mock_cfg:
        mock_cfg.DATABASE_PATH = db_path
        _health_check_job()
    mock_hc.assert_called_once()


def test_health_check_job_sends_alert_when_problems_found():
    with patch("scripts.run_scheduler.run_health_check", return_value=["[urgent] problem"]), \
         patch("scripts.run_scheduler.send_alert") as mock_alert, \
         patch("scripts.run_scheduler.config"):
        _health_check_job()
    mock_alert.assert_called_once()


def test_health_check_job_silent_when_no_problems():
    with patch("scripts.run_scheduler.run_health_check", return_value=[]), \
         patch("scripts.run_scheduler.send_alert") as mock_alert, \
         patch("scripts.run_scheduler.config"):
        _health_check_job()
    mock_alert.assert_not_called()
