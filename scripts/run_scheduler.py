import atexit
import json
import logging
import os
import signal
import subprocess
import sys
import tempfile
import time
from datetime import date, datetime
from typing import Optional

import schedule

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from scripts.backup_db import backup_database
from scripts.cleanup_profiles import cleanup_profiles
from scripts.export_csv import export_to_csv
from scripts.run_daily import run_collection
from src.browser_fetcher import install_browser_patch, shutdown_browser
from src.config_validator import validate_config
from src.date_generator import generate_target_dates
from src.frontend_csv_builder import build as build_frontend_csv
from src.health_checker import run_health_check
from src.html_generator import generate as generate_html
from src.log_config import setup_logging
from src.migrations import apply_migrations
from src.notifier import send_alert
from src.request_pacer import compute_sleep_intervals
from src.route_expander import expand_jobs

setup_logging()
logger = logging.getLogger(__name__)

PID_FILE = os.path.join(
    os.path.dirname(os.path.abspath(config.DATABASE_PATH)),
    "run_scheduler.pid",
)

_PRIORITY_RANK = {"urgent": 4, "high": 3, "default": 2, "low": 1, "min": 0}


def _write_pid_file() -> None:
    """Write the current process PID to PID_FILE atomically.

    Uses a temp-file + os.replace so the file is never partially written.
    The directory is created if it does not yet exist.
    """
    target_dir = os.path.dirname(os.path.abspath(PID_FILE))
    os.makedirs(target_dir, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        dir=target_dir,
        delete=False,
    ) as f:
        f.write(str(os.getpid()))
        f.flush()
        os.fsync(f.fileno())
        tmp = f.name
    os.replace(tmp, PID_FILE)
    logger.debug("PID file written: %s (pid=%d)", PID_FILE, os.getpid())


def _remove_pid_file() -> None:
    """Remove the PID file; harmless if it is already absent."""
    try:
        os.remove(PID_FILE)
        logger.debug("PID file removed: %s", PID_FILE)
    except FileNotFoundError:
        pass


def _check_stale_pid_file() -> Optional[int]:
    """Check for a pre-existing PID file and determine whether it is stale.

    Returns:
        None  — safe to proceed (no file, stale file cleaned up, or malformed
                file cleaned up).
        int   — a live process owns the PID file; caller should refuse to start.

    Note: On Windows, os.kill(pid, 0) may raise OSError (not ProcessLookupError)
    for dead processes. This is handled by catching OSError as "not alive".
    """
    if not os.path.exists(PID_FILE):
        return None

    try:
        with open(PID_FILE) as f:
            pid = int(f.read().strip())
    except (ValueError, OSError):
        logger.warning("PID file is malformed; removing: %s", PID_FILE)
        _remove_pid_file()
        return None

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        logger.info(
            "Removing stale PID file from previous run (pid=%d was dead): %s",
            pid,
            PID_FILE,
        )
        _remove_pid_file()
        return None
    except PermissionError:
        # Process exists but is owned by another user — treat as alive.
        return pid
    except OSError:
        # On Windows, os.kill(pid, 0) may raise OSError (not ProcessLookupError)
        # for a dead process. Treat any OSError as "process not alive".
        logger.info(
            "Removing stale PID file (pid=%d not alive or inaccessible): %s",
            pid,
            PID_FILE,
        )
        _remove_pid_file()
        return None

    return pid


def _highest_priority(problems: list) -> str:
    best = "default"
    for problem in problems:
        for level in _PRIORITY_RANK:
            if f"[{level}]" in problem and _PRIORITY_RANK[level] > _PRIORITY_RANK[best]:
                best = level
    return best


def _daily_job(heartbeat_path: Optional[str] = None) -> None:
    """Run one full collection cycle. Called by the scheduler at window start."""
    from datetime import date

    logger.info("Scheduler: starting daily collection")
    try:
        dates = generate_target_dates(date.today())
        jobs = expand_jobs(config.ROUTES, dates)
        intervals = compute_sleep_intervals(
            len(jobs),
            config.DAILY_WINDOW_START_HOUR,
            config.DAILY_WINDOW_END_HOUR,
        )
        if heartbeat_path is None:
            heartbeat_path = os.path.join(
                os.path.dirname(os.path.abspath(config.DATABASE_PATH)), "last_run.json"
            )

        run_collection(jobs, config.DATABASE_PATH, heartbeat_path, intervals)
        logger.info("Scheduler: daily collection finished")
    except Exception as exc:
        logger.error("Daily collection failed: %s", exc)
        send_alert(
            title="Flight tracker: daily collection failed",
            message=str(exc),
            priority="high",
        )


def _backup_job() -> None:
    """Back up the database and alert via ntfy if the backup fails."""
    logger.info("Scheduler: starting backup")
    try:
        path = backup_database(
            config.DATABASE_PATH,
            config.BACKUP_DIR,
            config.BACKUP_KEEP_LAST_N,
            offsite_dir=getattr(config, "BACKUP_OFFSITE_DIR", ""),
        )
        logger.info("Scheduler: backup written to %s", path)
    except Exception as exc:
        logger.error("Backup failed: %s", exc)
        send_alert(
            title="Flight tracker: backup failed",
            message=str(exc),
            priority="high",
        )


def _csv_export_job() -> None:
    """Export the full observations table to CSV. Called by the scheduler at 23:45."""
    logger.info("Scheduler: exporting CSV")
    try:
        output_path = os.path.join(
            os.path.dirname(os.path.abspath(config.DATABASE_PATH)), "flights_export.csv"
        )
        count = export_to_csv(config.DATABASE_PATH, output_path)
        logger.info("Scheduler: exported %d rows to %s", count, output_path)
    except Exception as exc:
        logger.error("CSV export failed: %s", exc)
        send_alert(
            title="Flight tracker: CSV export failed",
            message=str(exc),
            priority="high",
        )


def _frontend_csv_job() -> None:
    """Build the slim frontend CSV from flights_export.csv. Called by the
    scheduler at 23:46, one minute after the full CSV export at 23:45."""
    logger.info("Scheduler: building frontend CSV")
    try:
        data_dir = os.path.dirname(os.path.abspath(config.DATABASE_PATH))
        input_path = os.path.join(data_dir, "flights_export.csv")
        output_path = os.path.join(data_dir, "flights_frontend.csv")
        written, status = build_frontend_csv(input_path, output_path)
        logger.info(
            "Scheduler: frontend CSV finished — rows=%d status=%s output=%s",
            written,
            status,
            output_path,
        )
    except Exception as exc:
        logger.error("Frontend CSV build failed: %s", exc)
        send_alert(
            title="Flight tracker: frontend CSV build failed",
            message=str(exc),
            priority="high",
        )
        return  # Skip HTML chain when the slim CSV is missing/stale.

    # Chain the HTML build inline so it runs as soon as the slim CSV is
    # ready — no fixed-time schedule entry, which would race when the CSV
    # job overruns its expected window.
    try:
        _generate_html_job()
    except Exception:  # noqa: BLE001
        # _generate_html_job already alerts; suppress here to keep the
        # CSV job's own status accurate.
        logger.exception("HTML chain from frontend_csv_job failed")


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_OUTPUT_PATH = os.path.join(REPO_ROOT, "frontend", "index.html")


def _generate_html_job() -> None:
    """Generate the self-contained frontend HTML. Triggered inline at the
    end of _frontend_csv_job so the page is regenerated as soon as the
    slim CSV is fresh — no separate timed entry, no timing race."""
    logger.info("Scheduler: generating frontend HTML")
    data_dir = os.path.dirname(os.path.abspath(config.DATABASE_PATH))
    input_path = os.path.join(data_dir, "flights_frontend.csv")
    output_path = FRONTEND_OUTPUT_PATH
    try:
        n = generate_html(input_path, output_path, inline_data=True)
        logger.info("Scheduler: HTML generated — rows=%d output=%s", n, output_path)
    except Exception as exc:  # noqa: BLE001
        logger.error("HTML generation failed: %s", exc)
        send_alert(
            title="Flight tracker: HTML generation failed",
            message=str(exc),
            priority="high",
        )


def _cleanup_profiles_job() -> None:
    """Prune Playwright profile dir if oversized. Runs weekly."""
    logger.info("Scheduler: running browser-profile cleanup")
    try:
        from pathlib import Path

        profiles_dir = (
            Path(os.path.dirname(os.path.abspath(config.DATABASE_PATH)))
            / "browser_profiles"
        )
        max_bytes = getattr(config, "BROWSER_PROFILE_MAX_BYTES", 300_000_000)
        cleanup_profiles(profiles_dir, max_bytes)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Browser-profile cleanup failed: %s", exc)


def _health_check_job() -> None:
    """Run the health check and alert if problems found.

    Called by the scheduler at 23:30.
    """
    logger.info("Scheduler: running health check")
    try:
        problems = run_health_check(config.DATABASE_PATH)
    except Exception as exc:
        logger.error("Health check failed: %s", exc)
        send_alert(
            title="Flight tracker: health check failed",
            message=str(exc),
            priority="high",
        )
        return
    if not problems:
        logger.info("Scheduler: health check passed")
        return
    for problem in problems:
        logger.warning("Health check problem: %s", problem)
    priority = _highest_priority(problems)
    send_alert(
        title=f"Flight tracker: {len(problems)} problem(s) detected",
        message="\n".join(problems),
        priority=priority,
    )


def _auto_update_job() -> None:
    """Spawn update.ps1 detached and exit, then let update.ps1 restart us.

    update.ps1 used to kill this scheduler via the PID file and then run the
    update — but subprocess.run waited on a powershell child whose first act
    was to kill its own parent, so the post-run alert path here was unreachable
    in production. We now detach the child (so it survives our exit), then
    exit cleanly. update.ps1 sees a stale PID file, runs the update, posts its
    own ntfy alert on failure, and starts a fresh scheduler.
    """
    update_script = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "update.ps1"
    )
    if not os.path.exists(update_script):
        logger.info("update.ps1 not found; skipping auto-update")
        return
    try:
        logger.info("Spawning detached auto-update; scheduler will exit")
        # Windows: detach so the child outlives this Python process.
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        creationflags = (
            DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        )
        log_path = os.path.join(
            os.path.dirname(os.path.abspath(config.DATABASE_PATH)), "update.log"
        )
        log_file = open(log_path, "a")  # noqa: SIM115
        subprocess.Popen(
            ["powershell", "-ExecutionPolicy", "Bypass", "-File", update_script],
            creationflags=creationflags,
            close_fds=True,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
        log_file.close()
        # Give the OS a moment to actually detach the child before we exit.
        time.sleep(2)
    except Exception as exc:
        logger.exception("Auto-update spawn failed: %s", exc)
        send_alert(
            title="Flight tracker: auto-update spawn failed",
            message=str(exc),
            priority="high",
        )
        return
    # os._exit bypasses schedule.run_pending's loop and any finally blocks.
    # update.ps1 will start a fresh scheduler when it finishes.
    logger.info("Auto-update spawned; exiting scheduler now")
    os._exit(0)


def setup_schedule() -> None:
    """Register all recurring jobs."""
    daily_time = f"{config.DAILY_WINDOW_START_HOUR:02d}:00"
    schedule.every().day.at(daily_time).do(_daily_job)
    schedule.every().day.at("01:00").do(_backup_job)
    schedule.every().day.at("23:30").do(_health_check_job)
    schedule.every().day.at("23:45").do(_csv_export_job)
    schedule.every().day.at("23:50").do(_frontend_csv_job)
    #schedule.every().day.at("23:55").do(_auto_update_job)
    schedule.every().monday.at("02:30").do(_cleanup_profiles_job)
    logger.info(
        "Scheduler: daily collection at %s, backup at 01:00, health check at "
        "23:30, CSV export at 23:45, frontend CSV at 23:50, "
        "weekly browser-profile cleanup Mon 02:30 "
        "(HTML regenerates inline after the frontend CSV completes)",
        daily_time,
    )


def _signal_handler(signum: int, frame) -> None:
    """Graceful shutdown on SIGTERM (systemd stop, Docker stop, etc.)."""
    logger.info("Scheduler received signal %d, shutting down", signum)
    _remove_pid_file()
    sys.exit(0)


def main() -> None:
    signal.signal(signal.SIGTERM, _signal_handler)
    validate_config(vars(config))

    existing = _check_stale_pid_file()
    if existing is not None:
        logger.error("Scheduler already running (PID %d). Refusing to start.", existing)
        sys.exit(1)
    _write_pid_file()

    try:
        applied = apply_migrations(config.DATABASE_PATH)
        logger.info("Scheduler: applied %d migration(s) on startup", applied)
        install_browser_patch()
        atexit.register(shutdown_browser)
        setup_schedule()
        logger.info("Scheduler running — press Ctrl+C to stop")

        # All time comparisons use local server time (not UTC) to match the configured
        # window hours (DAILY_WINDOW_START_HOUR, DAILY_WINDOW_END_HOUR).
        # Date comparisons use local date (date.today()) for consistency.
        now = datetime.now()
        if config.DAILY_WINDOW_START_HOUR <= now.hour < config.DAILY_WINDOW_END_HOUR:
            # Check if today's run already happened (guards against post-reboot re-runs)
            heartbeat_path = os.path.join(
                os.path.dirname(os.path.abspath(config.DATABASE_PATH)), "last_run.json"
            )
            today_str = date.today().isoformat()
            already_ran_today = False
            if os.path.exists(heartbeat_path):
                try:
                    with open(heartbeat_path) as f:
                        heartbeat = json.load(f)
                    if heartbeat.get("run_date") == today_str:
                        already_ran_today = True
                        logger.info(
                            "Today's collection already ran at startup; skipping"
                        )
                except (json.JSONDecodeError, OSError):
                    logger.warning(
                        "Could not read heartbeat file; proceeding with collection"
                    )

            if not already_ran_today:
                logger.info(
                    "Started within the operating window. "
                    "Executing immediate collection with compressed intervals."
                )
                _daily_job()

        try:
            while True:
                schedule.run_pending()
                time.sleep(60)
        except KeyboardInterrupt:
            logger.info("Scheduler stopped by user")
    finally:
        _remove_pid_file()


if __name__ == "__main__":
    main()
