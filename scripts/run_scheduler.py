import logging
import os
import sys
import time
from typing import Optional

import schedule

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from src.config_validator import validate_config
from src.date_generator import generate_target_dates
from src.health_checker import run_health_check
from src.log_config import setup_logging
from src.notifier import send_alert
from src.request_pacer import compute_sleep_intervals
from src.route_expander import expand_jobs
from scripts.backup_db import backup_database
from scripts.export_csv import export_to_csv
from src.frontend_csv_builder import build as build_frontend_csv
from src.html_generator import generate as generate_html
from scripts.run_daily import run_collection

setup_logging()
logger = logging.getLogger(__name__)

_PRIORITY_RANK = {"urgent": 4, "high": 3, "default": 2, "low": 1, "min": 0}


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


def _backup_job() -> None:
    """Back up the database and alert via ntfy if the backup fails."""
    logger.info("Scheduler: starting backup")
    try:
        path = backup_database(
            config.DATABASE_PATH, config.BACKUP_DIR, config.BACKUP_KEEP_LAST_N
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
    output_path = os.path.join(
        os.path.dirname(os.path.abspath(config.DATABASE_PATH)), "flights_export.csv"
    )
    count = export_to_csv(config.DATABASE_PATH, output_path)
    logger.info("Scheduler: exported %d rows to %s", count, output_path)


def _frontend_csv_job() -> None:
    """Build the slim frontend CSV from flights_export.csv. Called by the
    scheduler at 23:46, one minute after the full CSV export at 23:45."""
    logger.info("Scheduler: building frontend CSV")
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
        n = generate_html(input_path, output_path)
        logger.info("Scheduler: HTML generated — rows=%d output=%s", n, output_path)
    except Exception as exc:  # noqa: BLE001
        logger.error("HTML generation failed: %s", exc)
        send_alert(
            title="Flight tracker: HTML generation failed",
            message=str(exc),
            priority="high",
        )


def _health_check_job() -> None:
    """Run the health check and alert if problems found. Called by the scheduler at 23:30."""
    logger.info("Scheduler: running health check")
    problems = run_health_check(config.DATABASE_PATH)
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


def setup_schedule() -> None:
    """Register all recurring jobs."""
    daily_time = f"{config.DAILY_WINDOW_START_HOUR:02d}:00"
    schedule.every().day.at(daily_time).do(_daily_job)
    schedule.every().day.at("01:00").do(_backup_job)
    schedule.every().day.at("23:30").do(_health_check_job)
    schedule.every().day.at("23:45").do(_csv_export_job)
    schedule.every().day.at("23:46").do(_frontend_csv_job)
    logger.info(
        "Scheduler: daily collection at %s, backup at 01:00, health check at "
        "23:30, CSV export at 23:45, frontend CSV at 23:46 "
        "(HTML regenerates inline after the frontend CSV completes)",
        daily_time,
    )


def main() -> None:
    validate_config(vars(config))
    setup_schedule()
    logger.info("Scheduler running — press Ctrl+C to stop")

    from datetime import datetime

    now = datetime.now()
    if config.DAILY_WINDOW_START_HOUR <= now.hour < config.DAILY_WINDOW_END_HOUR:
        logger.info(
            "Started within the operating window. Executing immediate collection with compressed intervals."
        )
        _daily_job()

    try:
        while True:
            schedule.run_pending()
            time.sleep(60)
    except KeyboardInterrupt:
        logger.info("Scheduler stopped by user")


if __name__ == "__main__":
    main()
