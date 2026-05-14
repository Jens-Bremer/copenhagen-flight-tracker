import json
import logging
import os
import sys
import time
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from src.database import insert_observations
from src.date_generator import generate_target_dates
from src.flight_fetcher import fetch_flights_for_date
from src.request_pacer import compute_sleep_intervals, seconds_until_window_start
from src.response_parser import parse_flights
from src.route_expander import expand_jobs

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def _write_heartbeat(run_date: str, total_observations: int, failed_jobs_count: int, duration_seconds: float) -> None:
    os.makedirs("data", exist_ok=True)
    with open("data/last_run.json", "w") as f:
        json.dump({
            "run_date": run_date,
            "total_observations": total_observations,
            "failed_jobs_count": failed_jobs_count,
            "duration_seconds": round(duration_seconds, 1),
        }, f, indent=2)


def main() -> None:
    start_time = time.monotonic()
    run_date = date.today().isoformat()
    logger.info("Starting daily flight price collection (%s)", run_date)

    # Step 1 — target dates
    dates = generate_target_dates(date.today())
    logger.info("Targeting %d departure dates", len(dates))

    # Step 2 — job list
    jobs = expand_jobs(config.ROUTES, dates)
    total_jobs = len(jobs)
    logger.info("Expanded to %d jobs (routes × dates)", total_jobs)

    # Step 3 — pacing intervals
    intervals = compute_sleep_intervals(
        total_jobs,
        config.DAILY_WINDOW_START_HOUR,
        config.DAILY_WINDOW_END_HOUR,
    )

    # Step 4 — wait for window to open
    wait = seconds_until_window_start(config.DAILY_WINDOW_START_HOUR)
    if wait > 0:
        logger.info("Window opens in %.0f seconds — waiting", wait)
        time.sleep(wait)

    # Step 5 — main loop
    total_observations = 0
    failed_jobs = []

    for idx, (origin, destination, departure_date) in enumerate(jobs, start=1):
        logger.info(
            "Querying %s→%s %s [%d/%d]",
            origin, destination, departure_date, idx, total_jobs,
        )
        try:
            result = fetch_flights_for_date(origin, destination, departure_date)
            observations = parse_flights(
                result, origin, destination, departure_date,
                datetime.now(tz=timezone.utc),
            )
            inserted = insert_observations(config.DATABASE_PATH, observations)
            total_observations += inserted
            logger.info("Stored %d flights", inserted)
            if inserted == 0:
                failed_jobs.append((origin, destination, departure_date))
        except Exception as exc:
            logger.error("Job %s→%s %s failed: %s", origin, destination, departure_date, exc)
            failed_jobs.append((origin, destination, departure_date))

        if idx < total_jobs:
            time.sleep(intervals[idx - 1])

    # Step 6 — summary
    duration = time.monotonic() - start_time
    logger.info(
        "Daily collection complete. Total observations: %d. Failed jobs: %d.",
        total_observations, len(failed_jobs),
    )
    if failed_jobs:
        for origin, destination, dep_date in failed_jobs:
            logger.warning("Failed: %s→%s %s", origin, destination, dep_date)

    _write_heartbeat(run_date, total_observations, len(failed_jobs), duration)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Interrupted by user — exiting.")
        sys.exit(0)
