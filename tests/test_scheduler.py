"""Tests for run_scheduler: job registration and callable job functions."""

import json
import os
import sys
from unittest.mock import patch

import pytest
import schedule

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from scripts.run_daily import _write_heartbeat
from scripts.run_scheduler import (
    _auto_update_job,
    _backup_job,
    _check_stale_pid_file,
    _csv_export_job,
    _daily_job,
    _frontend_csv_job,
    _generate_html_job,
    _health_check_job,
    _remove_pid_file,
    _write_pid_file,
    setup_schedule,
)


@pytest.fixture(autouse=True)
def clear_schedule():
    """Ensure each test starts with a clean schedule."""
    schedule.clear()
    yield
    schedule.clear()


# --- Job registration ---


def test_setup_schedule_registers_six_jobs():
    """Six scheduled jobs: daily collection, backup, health check, CSV export,
    frontend CSV, auto-update. HTML generation has no separate entry — it chains
    inline after the frontend CSV job completes."""
    setup_schedule()
    assert len(schedule.jobs) == 6


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
        mock_cfg.BACKUP_OFFSITE_DIR = ""
        _backup_job()
    mock_bk.assert_called_once_with(db_path, backup_dir, 7, offsite_dir="")


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
    args, kwargs = mock_gen.call_args
    # Input still reads from the data dir (alongside flights.db)
    assert args[0].endswith("flights_frontend.csv")
    # Output now lives in the committed frontend/ dir, not data/
    assert args[1].endswith(os.path.join("frontend", "index.html"))
    # Must inline the data blobs so the airline page renders
    assert kwargs.get("inline_data") is True


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


def test_auto_update_scheduled_at_2355():
    """Auto-update job is registered at 23:55."""
    setup_schedule()
    times = [str(job.next_run.strftime("%H:%M")) for job in schedule.jobs]
    assert "23:55" in times


def test_auto_update_job_skips_when_script_missing(tmp_path):
    """When update.ps1 does not exist, the job logs a message and returns."""
    with (
        patch("scripts.run_scheduler.os.path.exists", return_value=False),
        patch("scripts.run_scheduler.logger") as mock_logger,
    ):
        _auto_update_job()
    mock_logger.info.assert_called_once()
    assert "not found" in mock_logger.info.call_args[0][0].lower()


def test_auto_update_job_runs_powershell_script(tmp_path):
    """The auto-update job calls powershell with update.ps1."""
    update_script = str(tmp_path / "update.ps1")
    mock_result = type("R", (), {"returncode": 0})()
    with (
        patch("scripts.run_scheduler.os.path.exists", return_value=True),
        patch(
            "scripts.run_scheduler.subprocess.run", return_value=mock_result
        ) as mock_run,
        patch("scripts.run_scheduler.os.path.dirname", return_value=str(tmp_path)),
        patch("scripts.run_scheduler.os.path.abspath", return_value=update_script),
    ):
        _auto_update_job()
    mock_run.assert_called_once()
    (args, _kwargs) = mock_run.call_args
    cmd = args[0]
    assert cmd[0] == "powershell"
    assert "-ExecutionPolicy" in cmd
    assert "Bypass" in cmd
    assert "-File" in cmd
    assert cmd[-1] == update_script


def test_auto_update_job_sends_alert_on_failure():
    """When update.ps1 fails (non-zero exit), the job sends an alert."""
    with (
        patch("scripts.run_scheduler.os.path.exists", return_value=True),
        patch(
            "scripts.run_scheduler.subprocess.run",
            return_value=type("R", (), {"returncode": 1, "stderr": "error"})(),
        ),
        patch("scripts.run_scheduler.send_alert") as mock_alert,
    ):
        _auto_update_job()
    mock_alert.assert_called_once()
    _args, kwargs = mock_alert.call_args
    assert "auto-update" in kwargs["title"].lower()
    assert kwargs["priority"] == "high"


def test_auto_update_job_sends_alert_on_crash():
    """When update.ps1 subprocess raises an exception, the job sends an alert."""
    with (
        patch("scripts.run_scheduler.os.path.exists", return_value=True),
        patch(
            "scripts.run_scheduler.subprocess.run",
            side_effect=RuntimeError("timeout"),
        ),
        patch("scripts.run_scheduler.send_alert") as mock_alert,
    ):
        _auto_update_job()
    mock_alert.assert_called_once()
    _args, kwargs = mock_alert.call_args
    assert "auto-update" in kwargs["title"].lower()
    assert kwargs["priority"] == "high"


def test_auto_update_job_silent_on_success():
    """When update.ps1 succeeds (exit 0), the job logs success and does not alert."""
    with (
        patch("scripts.run_scheduler.os.path.exists", return_value=True),
        patch(
            "scripts.run_scheduler.subprocess.run",
            return_value=type("R", (), {"returncode": 0})(),
        ),
        patch("scripts.run_scheduler.send_alert") as mock_alert,
        patch("scripts.run_scheduler.logger") as mock_logger,
    ):
        _auto_update_job()
    mock_alert.assert_not_called()
    # Should log success
    success_calls = [
        c for c in mock_logger.info.call_args_list if "succeeded" in str(c).lower()
    ]
    assert len(success_calls) > 0


# --- PID file management (issue #133) ---


def test_write_pid_file_creates_file_with_current_pid(tmp_path, monkeypatch):
    """_write_pid_file() must create the PID file containing the current PID."""
    pid_file = tmp_path / "run_scheduler.pid"
    monkeypatch.setattr("scripts.run_scheduler.PID_FILE", str(pid_file))
    _write_pid_file()
    assert pid_file.exists()
    assert int(pid_file.read_text().strip()) == os.getpid()


def test_remove_pid_file_removes_existing_file(tmp_path, monkeypatch):
    """_remove_pid_file() must delete the PID file when it exists."""
    pid_file = tmp_path / "run_scheduler.pid"
    pid_file.write_text(str(os.getpid()))
    monkeypatch.setattr("scripts.run_scheduler.PID_FILE", str(pid_file))
    _remove_pid_file()
    assert not pid_file.exists()


def test_remove_pid_file_tolerates_absent_file(tmp_path, monkeypatch):
    """_remove_pid_file() must not raise when the PID file does not exist."""
    pid_file = tmp_path / "run_scheduler.pid"
    monkeypatch.setattr("scripts.run_scheduler.PID_FILE", str(pid_file))
    # Should not raise
    _remove_pid_file()


def test_check_stale_pid_file_returns_none_when_absent(tmp_path, monkeypatch):
    """_check_stale_pid_file() returns None when no PID file exists."""
    pid_file = tmp_path / "run_scheduler.pid"
    monkeypatch.setattr("scripts.run_scheduler.PID_FILE", str(pid_file))
    assert _check_stale_pid_file() is None


def test_check_stale_pid_file_returns_pid_when_process_alive(tmp_path, monkeypatch):
    """_check_stale_pid_file() returns the PID when the process is alive."""
    pid_file = tmp_path / "run_scheduler.pid"
    live_pid = 99999
    pid_file.write_text(str(live_pid))
    monkeypatch.setattr("scripts.run_scheduler.PID_FILE", str(pid_file))
    # os.kill(pid, 0) not raising means the process exists
    with patch("scripts.run_scheduler.os.kill"):
        result = _check_stale_pid_file()
    assert result == live_pid
    # File must still exist — we don't clean up a live process's PID file
    assert pid_file.exists()


def test_check_stale_pid_file_cleans_up_dead_pid(tmp_path, monkeypatch):
    """_check_stale_pid_file() removes the file and returns None when PID is dead."""
    pid_file = tmp_path / "run_scheduler.pid"
    dead_pid = 99999
    pid_file.write_text(str(dead_pid))
    monkeypatch.setattr("scripts.run_scheduler.PID_FILE", str(pid_file))
    with patch("scripts.run_scheduler.os.kill", side_effect=ProcessLookupError):
        result = _check_stale_pid_file()
    assert result is None
    assert not pid_file.exists()


def test_check_stale_pid_file_cleans_up_malformed_file(tmp_path, monkeypatch):
    """_check_stale_pid_file() removes a malformed PID file and returns None."""
    pid_file = tmp_path / "run_scheduler.pid"
    pid_file.write_text("not-a-pid")
    monkeypatch.setattr("scripts.run_scheduler.PID_FILE", str(pid_file))
    result = _check_stale_pid_file()
    assert result is None
    assert not pid_file.exists()


# --- Atomic heartbeat write (issue #115) ---


def test_write_heartbeat_leaves_prior_content_intact_on_mid_write_crash(tmp_path):
    """If json.dump raises mid-write, the target file must remain intact (its
    prior content) or be absent — never a partial/empty file. This guards
    against the failure mode where the health checker reads an empty
    last_run.json and reports a misleading 'stale' message."""
    heartbeat_path = str(tmp_path / "last_run.json")
    # Seed with valid prior content from a previous successful run.
    prior = {
        "run_date": "2026-05-16",
        "total_observations": 99,
        "failed_jobs_count": 0,
        "total_jobs": 100,
        "duration_seconds": 1234.5,
        "failures_by_kind": {
            "bot_challenge": 0,
            "rate_limited": 0,
            "parse_error": 0,
            "network": 0,
            "other": 0,
        },
    }
    with open(heartbeat_path, "w") as f:
        json.dump(prior, f)

    with patch("scripts.run_daily.json.dump", side_effect=RuntimeError("disk full")):
        with pytest.raises(RuntimeError, match="disk full"):
            _write_heartbeat(
                heartbeat_path,
                run_date="2026-05-17",
                total_observations=100,
                failed_jobs_count=0,
                total_jobs=100,
                duration_seconds=42.0,
            )

    # The target file must be unchanged — atomic rename never happened.
    with open(heartbeat_path) as f:
        actual = json.load(f)
    assert actual == prior

    # No stray temp files leaked into the directory (besides the heartbeat
    # itself); tempfile.NamedTemporaryFile(delete=False) leaves the temp file
    # on disk after a crash, but it must NOT have clobbered the target.
    # The temp file is acceptable — what matters is target integrity.
    assert os.path.exists(heartbeat_path)


def test_write_heartbeat_persists_failures_by_kind(tmp_path):
    """The heartbeat must persist the per-category failure counters so the
    health checker can read them (issue #111). Default of None must serialize
    as a fresh zero-filled dict — never absent, never null — so downstream
    consumers can rely on the field's presence."""
    heartbeat_path = str(tmp_path / "last_run.json")
    failures = {
        "bot_challenge": 4,
        "rate_limited": 1,
        "parse_error": 0,
        "network": 2,
        "other": 0,
    }
    _write_heartbeat(
        heartbeat_path,
        run_date="2026-05-17",
        total_observations=42,
        failed_jobs_count=7,
        total_jobs=100,
        duration_seconds=10.0,
        failures_by_kind=failures,
    )
    with open(heartbeat_path) as f:
        data = json.load(f)
    assert data["failures_by_kind"] == failures


def test_write_heartbeat_defaults_failures_by_kind_to_zero_counts(tmp_path):
    """Omitting failures_by_kind must still write a zero-filled dict so
    consumers never see a missing field."""
    heartbeat_path = str(tmp_path / "last_run.json")
    _write_heartbeat(
        heartbeat_path,
        run_date="2026-05-17",
        total_observations=42,
        failed_jobs_count=0,
        total_jobs=100,
        duration_seconds=10.0,
    )
    with open(heartbeat_path) as f:
        data = json.load(f)
    assert data["failures_by_kind"] == {
        "bot_challenge": 0,
        "rate_limited": 0,
        "parse_error": 0,
        "network": 0,
        "other": 0,
    }


def test_write_heartbeat_calls_os_replace_once_with_temp_and_target(tmp_path):
    """The atomic-write idiom must use os.replace exactly once, with the temp
    path as source and the target heartbeat path as destination. This guards
    against accidental regressions to a naive open()+write that would bypass
    the atomic-rename step."""
    heartbeat_path = str(tmp_path / "last_run.json")

    with patch("scripts.run_daily.os.replace") as mock_replace:
        _write_heartbeat(
            heartbeat_path,
            run_date="2026-05-17",
            total_observations=100,
            failed_jobs_count=0,
            total_jobs=100,
            duration_seconds=42.0,
        )

    mock_replace.assert_called_once()
    args, _kwargs = mock_replace.call_args
    src, dst = args
    # Source must be a temp file in the same directory as the target — a
    # cross-filesystem rename is non-atomic on POSIX.
    assert os.path.dirname(src) == os.path.dirname(os.path.abspath(heartbeat_path))
    assert os.path.basename(src).startswith(".last_run.")
    assert os.path.basename(src).endswith(".tmp")
    # Destination must be exactly the target heartbeat path.
    assert dst == heartbeat_path
