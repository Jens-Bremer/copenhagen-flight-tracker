"""Tests for run_scheduler: job registration and callable job functions."""

import os
import sys
from unittest.mock import patch

import schedule
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from scripts.run_scheduler import (
    setup_schedule,
    _daily_job,
    _health_check_job,
    _csv_export_job,
    _backup_job,
    _frontend_csv_job,
    _generate_html_job,
)


@pytest.fixture(autouse=True)
def clear_schedule():
    """Ensure each test starts with a clean schedule."""
    schedule.clear()
    yield
    schedule.clear()


# --- Job registration ---


def test_setup_schedule_registers_five_jobs():
    """Five scheduled jobs: daily collection, backup, health check, CSV export,
    frontend CSV. HTML generation has no separate entry — it chains inline
    after the frontend CSV job completes."""
    setup_schedule()
    assert len(schedule.jobs) == 5


def test_no_timed_html_generation_job():
    """The HTML generator must NOT have a separate timed schedule entry; it
    runs only via the inline chain from _frontend_csv_job. This guards
    against accidentally reintroducing a 23:47 race-prone fallback."""
    setup_schedule()
    times = [str(job.next_run.strftime("%H:%M")) for job in schedule.jobs]
    assert "23:47" not in times


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
    with (
        patch("scripts.run_scheduler.run_collection") as mock_run,
        patch("scripts.run_scheduler.generate_target_dates", return_value=[]),
        patch("scripts.run_scheduler.expand_jobs", return_value=[]),
        patch("scripts.run_scheduler.compute_sleep_intervals", return_value=[]),
        patch("scripts.run_scheduler.config") as mock_cfg,
    ):
        mock_cfg.ROUTES = config.ROUTES
        mock_cfg.DATABASE_PATH = db_path
        mock_cfg.DAILY_WINDOW_START_HOUR = config.DAILY_WINDOW_START_HOUR
        mock_cfg.DAILY_WINDOW_END_HOUR = config.DAILY_WINDOW_END_HOUR
        _daily_job(heartbeat_path=heartbeat_path)
    mock_run.assert_called_once()


def test_health_check_job_calls_run_health_check(tmp_path):
    db_path = str(tmp_path / "flights.db")
    with (
        patch("scripts.run_scheduler.run_health_check", return_value=[]) as mock_hc,
        patch("scripts.run_scheduler.config") as mock_cfg,
    ):
        mock_cfg.DATABASE_PATH = db_path
        _health_check_job()
    mock_hc.assert_called_once()


def test_health_check_job_sends_alert_when_problems_found():
    with (
        patch(
            "scripts.run_scheduler.run_health_check", return_value=["[urgent] problem"]
        ),
        patch("scripts.run_scheduler.send_alert") as mock_alert,
        patch("scripts.run_scheduler.config"),
    ):
        _health_check_job()
    mock_alert.assert_called_once()


def test_health_check_job_silent_when_no_problems():
    with (
        patch("scripts.run_scheduler.run_health_check", return_value=[]),
        patch("scripts.run_scheduler.send_alert") as mock_alert,
        patch("scripts.run_scheduler.config"),
    ):
        _health_check_job()
    mock_alert.assert_not_called()


def test_csv_export_scheduled_at_2345():
    setup_schedule()
    times = [str(job.next_run.strftime("%H:%M")) for job in schedule.jobs]
    assert "23:45" in times


def test_csv_export_job_calls_export_to_csv(tmp_path):
    db_path = str(tmp_path / "flights.db")
    with (
        patch("scripts.run_scheduler.export_to_csv", return_value=0) as mock_export,
        patch("scripts.run_scheduler.config") as mock_cfg,
    ):
        mock_cfg.DATABASE_PATH = db_path
        _csv_export_job()
    mock_export.assert_called_once()


def test_backup_scheduled_at_0100():
    setup_schedule()
    times = [str(job.next_run.strftime("%H:%M")) for job in schedule.jobs]
    assert "01:00" in times


def test_backup_job_calls_backup_database(tmp_path):
    db_path = str(tmp_path / "flights.db")
    backup_dir = str(tmp_path / "backups")
    with (
        patch(
            "scripts.run_scheduler.backup_database", return_value=str(tmp_path / "b.db")
        ) as mock_bk,
        patch("scripts.run_scheduler.config") as mock_cfg,
    ):
        mock_cfg.DATABASE_PATH = db_path
        mock_cfg.BACKUP_DIR = backup_dir
        mock_cfg.BACKUP_KEEP_LAST_N = 7
        _backup_job()
    mock_bk.assert_called_once_with(db_path, backup_dir, 7)


def test_backup_job_sends_alert_on_failure():
    with (
        patch(
            "scripts.run_scheduler.backup_database", side_effect=OSError("disk full")
        ),
        patch("scripts.run_scheduler.send_alert") as mock_alert,
        patch("scripts.run_scheduler.config"),
    ):
        _backup_job()
    mock_alert.assert_called_once()
    _, kwargs = mock_alert.call_args
    assert kwargs["priority"] == "high"
    assert "backup" in kwargs["title"].lower()
    assert kwargs["message"] == "disk full"


def test_backup_job_silent_on_success(tmp_path):
    with (
        patch(
            "scripts.run_scheduler.backup_database", return_value=str(tmp_path / "b.db")
        ),
        patch("scripts.run_scheduler.send_alert") as mock_alert,
        patch("scripts.run_scheduler.config"),
    ):
        _backup_job()
    mock_alert.assert_not_called()


def test_frontend_csv_export_scheduled_at_2346():
    setup_schedule()
    times = [str(job.next_run.strftime("%H:%M")) for job in schedule.jobs]
    assert "23:46" in times


def test_frontend_csv_job_calls_build(tmp_path):
    with (
        patch(
            "scripts.run_scheduler.build_frontend_csv", return_value=(3, "ok")
        ) as mock_build,
        patch("scripts.run_scheduler.generate_html", return_value=3),
        patch("scripts.run_scheduler.config") as mock_cfg,
    ):
        mock_cfg.DATABASE_PATH = str(tmp_path / "flights.db")
        _frontend_csv_job()
    mock_build.assert_called_once()


def test_generate_html_job_calls_generate(tmp_path):
    with (
        patch("scripts.run_scheduler.generate_html", return_value=42) as mock_gen,
        patch("scripts.run_scheduler.config") as mock_cfg,
    ):
        mock_cfg.DATABASE_PATH = str(tmp_path / "flights.db")
        _generate_html_job()
    mock_gen.assert_called_once()
    args, _kwargs = mock_gen.call_args
    # Input still reads from the data dir (alongside flights.db)
    assert args[0].endswith("flights_frontend.csv")
    # Output now lives in the committed frontend/ dir, not data/
    assert args[1].endswith(os.path.join("frontend", "index.html"))


def test_generate_html_job_sends_alert_on_failure(tmp_path):
    with (
        patch("scripts.run_scheduler.generate_html", side_effect=RuntimeError("boom")),
        patch("scripts.run_scheduler.send_alert") as mock_alert,
        patch("scripts.run_scheduler.config") as mock_cfg,
    ):
        mock_cfg.DATABASE_PATH = str(tmp_path / "flights.db")
        _generate_html_job()
    mock_alert.assert_called_once()
    _args, kwargs = mock_alert.call_args
    assert kwargs["priority"] == "high"
    assert "HTML" in kwargs["title"]


def test_frontend_csv_job_chains_html_generation(tmp_path):
    """Verify the 23:46 frontend CSV job chains the HTML generation inline."""
    with (
        patch("scripts.run_scheduler.build_frontend_csv", return_value=(3, "ok")),
        patch("scripts.run_scheduler.generate_html", return_value=3) as mock_gen,
        patch("scripts.run_scheduler.config") as mock_cfg,
    ):
        mock_cfg.DATABASE_PATH = str(tmp_path / "flights.db")
        _frontend_csv_job()
    mock_gen.assert_called_once()
