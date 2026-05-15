import json
import logging
import os
import sys
import time
from datetime import date, datetime, timezone
from typing import Callable, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from src.config_validator import validate_config
from src.database import insert_observations
from src.log_config import setup_logging
from src.price_alerter import check_and_alert_cheap_flights
from src.date_generator import generate_target_dates
from src.flight_fetcher import fetch_flights_for_date
from src.request_pacer import compute_sleep_intervals, seconds_until_window_start
from src.response_parser import parse_flights
from src.route_expander import expand_jobs

setup_logging()
logger = logging.getLogger(__name__)


def _write_heartbeat(
    heartbeat_path: str,
    run_date: str,
    total_observations: int,
    failed_jobs_count: int,
    total_jobs: int,
    duration_seconds: float,
) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(heartbeat_path)), exist_ok=True)
    with open(heartbeat_path, "w") as f:
        json.dump(
            {
                "run_date": run_date,
                "total_observations": total_observations,
                "failed_jobs_count": failed_jobs_count,
                "total_jobs": total_jobs,
                "duration_seconds": round(duration_seconds, 1),
            },
            f,
            indent=2,
        )


def run_collection(
    jobs: list,
    db_path: str,
    heartbeat_path: str,
    intervals: Optional[list] = None,
    sleep_fn: Callable = time.sleep,
) -> Tuple[int, int]:
    """Execute one full collection cycle. Returns (total_observations, failed_jobs_count)."""
    start_time = time.monotonic()
    run_date = date.today().isoformat()
    total_jobs = len(jobs)

    if intervals is None:
        intervals = compute_sleep_intervals(
            total_jobs,
            config.DAILY_WINDOW_START_HOUR,
            config.DAILY_WINDOW_END_HOUR,
        )

    total_observations = 0
    failed_jobs = []

    for idx, (origin, destination, departure_date) in enumerate(jobs, start=1):
        logger.info(
            "Querying %s→%s %s [%d/%d]",
            origin,
            destination,
            departure_date,
            idx,
            total_jobs,
        )
        try:
            result = fetch_flights_for_date(
                origin, destination, departure_date, raise_on_failure=True
            )
            observations = parse_flights(
                result,
                origin,
                destination,
                departure_date,
                datetime.now(tz=timezone.utc),
            )
            inserted = insert_observations(db_path, observations)
            total_observations += inserted
            logger.info("Stored %d flights", inserted)
            if inserted == 0:
                failed_jobs.append(
                    (origin, destination, departure_date, "no observations stored")
                )
        except Exception as exc:
            logger.error(
                "Job %s→%s %s failed: %s", origin, destination, departure_date, exc
            )
            failed_jobs.append((origin, destination, departure_date, str(exc)))

        if idx < total_jobs and intervals:
            sleep_fn(intervals[idx - 1])

    duration = time.monotonic() - start_time
    logger.info(
        "Daily collection complete. Total observations: %d. Failed jobs: %d.",
        total_observations,
        len(failed_jobs),
    )
    if failed_jobs:
        for origin, destination, dep_date, reason in failed_jobs:
            logger.warning(
                "Failed: %s→%s %s (%s)", origin, destination, dep_date, reason
            )

    _write_heartbeat(
        heartbeat_path,
        run_date,
        total_observations,
        len(failed_jobs),
        total_jobs,
        duration,
    )
    check_and_alert_cheap_flights(db_path, config.PRICE_ALERT_THRESHOLD, run_date)
    return total_observations, len(failed_jobs)


def main() -> None:
    validate_config(vars(config))
    logger.info("Starting daily flight price collection (%s)", date.today().isoformat())

    dates = generate_target_dates(date.today())
    logger.info("Targeting %d departure dates", len(dates))

    jobs = expand_jobs(config.ROUTES, dates)
    logger.info("Expanded to %d jobs (routes × dates)", len(jobs))

    intervals = compute_sleep_intervals(
        len(jobs),
        config.DAILY_WINDOW_START_HOUR,
        config.DAILY_WINDOW_END_HOUR,
    )

    wait = seconds_until_window_start(config.DAILY_WINDOW_START_HOUR)
    if wait > 0:
        logger.info("Window opens in %.0f seconds — waiting", wait)
        time.sleep(wait)

    heartbeat_path = os.path.join(
        os.path.dirname(os.path.abspath(config.DATABASE_PATH)), "last_run.json"
    )
    run_collection(jobs, config.DATABASE_PATH, heartbeat_path, intervals)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Interrupted by user — exiting.")
        sys.exit(0)
