import atexit
import json
import logging
import os
import sys
import tempfile
import time
from datetime import date, datetime, timezone
from typing import Callable, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from scripts.collection import execute_single_job
from src.browser_fetcher import (
    get_last_route_label,
    install_browser_patch,
    reset_last_route_label,
    shutdown_browser,
)
from src.config_validator import validate_config
from src.date_generator import generate_target_dates
from src.flight_fetcher import (
    BotChallengeError,
    NetworkError,
    ParseError,
    RateLimitedError,
)
from src.log_config import setup_logging
from src.notifier import send_alert
from src.price_alerter import check_and_alert_cheap_flights
from src.request_pacer import compute_sleep_intervals, seconds_until_window_start
from src.route_expander import expand_jobs

setup_logging()
logger = logging.getLogger(__name__)

_SUMMARY_HOUR = 18
_FAILURE_SUMMARY_THRESHOLD = 3


def _build_failure_summary(
    failures_by_route: dict[str, int],
    failures_by_kind: dict[str, int],
    completed_jobs: int,
    total_jobs: int,
    now: datetime,
) -> tuple[str, str, str]:
    """Build the mid-run failure summary alert payload.

    Returns:
        (title, message, priority)
    """
    total_failures = sum(failures_by_route.values())
    failure_rate = total_failures / completed_jobs if completed_jobs else 0.0
    remaining_jobs = total_jobs - completed_jobs

    # Route breakdown with % of total failures: "direct=2 (67%), proxy=1 (33%)"
    route_parts = []
    for key, count in failures_by_route.items():
        if count <= 0:
            continue
        pct = int(count / total_failures * 100) if total_failures else 0
        route_parts.append(f"{key}={count} ({pct}%)")
    route_breakdown = ", ".join(route_parts) or "none"

    # Kind breakdown with % of total failures
    kind_label_map = {
        "bot_challenge": "bot challenge",
        "rate_limited": "rate limited",
        "parse_error": "parse error",
    }
    kind_parts = []
    for key, count in failures_by_kind.items():
        if count <= 0:
            continue
        label = kind_label_map.get(key, key).replace("_", " ")
        pct = int(count / total_failures * 100) if total_failures else 0
        kind_parts.append(f"{label}={count} ({pct}%)")
    kind_breakdown = ", ".join(kind_parts)

    is_blocked = bool(
        failures_by_kind.get("bot_challenge") or failures_by_kind.get("rate_limited")
    )
    lines = [
        f"Time: {now:%Y-%m-%d %H:%M}",
        f"Progress: {completed_jobs}/{total_jobs} complete ({remaining_jobs} left)",
        f"Failure rate: {total_failures}/{completed_jobs} failed ({failure_rate:.0%})",
        f"Route breakdown: {route_breakdown}",
    ]
    if kind_breakdown:
        lines.append(f"Failure types: {kind_breakdown}")
    if is_blocked:
        lines.append(
            "IP block detected — bot challenge or rate limit signals present."
            " Consider pausing or switching to proxy-only mode."
        )
    priority = "high" if is_blocked else "default"
    title = (
        f"Flight tracker: {total_failures} failures so far"
        f" ({failure_rate:.0%} of {completed_jobs} completed)"
    )
    return title, "\n".join(lines), priority


def _normalize_route_label(label: Optional[str]) -> str:
    """Normalize a route label to either 'direct' or 'proxy'."""
    if label in {"direct", "proxy"}:
        return label
    return "direct"


def _maybe_send_failure_summary(
    failures_by_route: dict[str, int],
    failures_by_kind: dict[str, int],
    completed_jobs: int,
    total_jobs: int,
    now: datetime,
    summary_sent: bool,
    allow_after_run: bool = False,
) -> bool:
    """Send the mid-run failure summary if thresholds are met.

    Returns True once a summary has been attempted.
    """
    if summary_sent:
        return True
    total_failures = sum(failures_by_route.values())
    if total_failures <= _FAILURE_SUMMARY_THRESHOLD:
        return False
    if not allow_after_run and now.hour < _SUMMARY_HOUR:
        return False
    title, message, priority = _build_failure_summary(
        failures_by_route=failures_by_route,
        failures_by_kind=failures_by_kind,
        completed_jobs=completed_jobs,
        total_jobs=total_jobs,
        now=now,
    )
    sent = send_alert(title=title, message=message, priority=priority)
    if sent:
        logger.info("Sent mid-run failure summary via ntfy (priority=%s)", priority)
    else:
        logger.error("Failed to send mid-run failure summary via ntfy")
    return True


def _empty_failures_by_kind() -> dict[str, int]:
    """Return a fresh per-category failure counter dict.

    Categories track the LEADING ban-signal taxonomy from issue #111:
    bot_challenge and rate_limited are the high-signal ones; parse_error
    isolates response-shape changes; network covers transport blips; other
    catches whatever fast_flights raises that doesn't fit the above.
    """
    return {
        "bot_challenge": 0,
        "rate_limited": 0,
        "parse_error": 0,
        "network": 0,
        "other": 0,
    }


def _classify_failure(exc: BaseException) -> str:
    """Map an exception raised by fetch_flights_for_date to a failure category."""
    if isinstance(exc, BotChallengeError):
        return "bot_challenge"
    if isinstance(exc, RateLimitedError):
        return "rate_limited"
    if isinstance(exc, ParseError):
        return "parse_error"
    if isinstance(exc, NetworkError):
        return "network"
    return "other"


def _write_heartbeat(
    heartbeat_path: str,
    run_date: str,
    total_observations: int,
    failed_jobs_count: int,
    total_jobs: int,
    duration_seconds: float,
    failures_by_kind: Optional[dict] = None,
) -> None:
    """Write the heartbeat file atomically via temp-file + os.replace.

    A naive ``open("w") + json.dump`` leaves the heartbeat empty or partial if
    the process dies mid-write. The health checker then either reports a
    misleading "stale" message or silently disables itself. Instead, write to
    a temp file in the same directory (so ``os.replace`` is atomic on POSIX),
    fsync it, and rename over the target. Either the old file survives intact
    or the new one fully replaces it — never a half-written intermediate.
    """
    target_dir = os.path.dirname(os.path.abspath(heartbeat_path))
    os.makedirs(target_dir, exist_ok=True)
    if failures_by_kind is None:
        failures_by_kind = _empty_failures_by_kind()
    # completed_at is an aware UTC timestamp written at the moment the
    # heartbeat is finalised. The dashboard uses it (not run_date, which is
    # date-only) to compute "X hours since last run".
    completed_at = datetime.now(timezone.utc).isoformat()
    with tempfile.NamedTemporaryFile(
        mode="w",
        dir=target_dir,
        prefix=".last_run.",
        suffix=".tmp",
        delete=False,
    ) as f:
        json.dump(
            {
                "run_date": run_date,
                "completed_at": completed_at,
                "total_observations": total_observations,
                "failed_jobs_count": failed_jobs_count,
                "total_jobs": total_jobs,
                "duration_seconds": round(duration_seconds, 1),
                "failures_by_kind": failures_by_kind,
            },
            f,
            indent=2,
        )
        f.flush()
        os.fsync(f.fileno())
        tmp = f.name
    os.replace(tmp, heartbeat_path)


def run_collection(
    jobs: list,
    db_path: str,
    heartbeat_path: str,
    intervals: Optional[list] = None,
    sleep_fn: Callable = time.sleep,
    now_fn: Callable[[], datetime] = datetime.now,
) -> tuple[int, int]:
    """Execute one full collection cycle.

    Returns (total_observations, failed_jobs_count).
    """
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
    summary_sent = False
    failures_by_route = {"direct": 0, "proxy": 0}
    failures_by_kind_so_far = _empty_failures_by_kind()
    # Per-category failure counters (issue #111). Only the final outcome of
    # each job counts: if the first pass raised BotChallengeError but the
    # retry succeeded, that job is NOT counted as a failure. We accomplish
    # this by tallying the retry results (if any) and otherwise the first
    # pass — the retry-pass loop below replaces failed_jobs, so we recompute
    # the totals from the final failed_jobs list.
    first_pass_exceptions: dict[tuple, BaseException] = {}

    for idx, (origin, destination, departure_date) in enumerate(jobs, start=1):
        logger.info(
            "Querying %s→%s %s [%d/%d]",
            origin,
            destination,
            departure_date,
            idx,
            total_jobs,
        )
        reset_last_route_label()
        inserted, exc = execute_single_job(origin, destination, departure_date, db_path)
        route_label = _normalize_route_label(get_last_route_label())
        if exc is not None:
            logger.error(
                "Job %s→%s %s failed: %s",
                origin,
                destination,
                departure_date,
                exc,
            )
            failed_jobs.append((origin, destination, departure_date, str(exc)))
            first_pass_exceptions[(origin, destination, departure_date)] = exc
            failures_by_route[route_label] += 1
            failures_by_kind_so_far[_classify_failure(exc)] += 1
        elif inserted == 0:
            logger.info("Stored 0 flights")
            failed_jobs.append(
                (origin, destination, departure_date, "no observations stored")
            )
            failures_by_route[route_label] += 1
            failures_by_kind_so_far["other"] += 1
        else:
            total_observations += inserted
            logger.info("Stored %d flights", inserted)

        summary_sent = _maybe_send_failure_summary(
            failures_by_route=failures_by_route,
            failures_by_kind=failures_by_kind_so_far,
            completed_jobs=idx,
            total_jobs=total_jobs,
            now=now_fn(),
            summary_sent=summary_sent,
        )
        if idx < total_jobs and intervals:
            sleep_fn(intervals[idx - 1])

    # Circuit-breaker: if we've seen a streak of 3+ bot challenges or rate
    # limits anywhere in this run (indicating an active block), skip the retry
    # pass. Retrying against an active block doubles request volume and makes
    # the situation worse.
    #
    # We track the LONGEST consecutive streak across failed_jobs, not the
    # trailing count — a single late non-block failure (e.g. a parse error on
    # the final job) must not disarm the breaker when the IP was clearly being
    # blocked earlier in the run.
    longest_streak = 0
    current_streak = 0
    for origin, destination, departure_date, _reason in failed_jobs:
        job_key = (origin, destination, departure_date)
        exc = first_pass_exceptions.get(job_key)
        if exc and _classify_failure(exc) in ("bot_challenge", "rate_limited"):
            current_streak += 1
            if current_streak > longest_streak:
                longest_streak = current_streak
        else:
            current_streak = 0

    circuit_breaker_triggered = longest_streak >= 3
    if circuit_breaker_triggered:
        logger.error(
            "Circuit-breaker triggered: %d consecutive bot challenges/rate limits. "
            "Skipping retry pass to avoid making the block worse.",
            longest_streak,
        )
        send_alert(
            title="Flight tracker: circuit breaker triggered",
            message=(
                f"Detected {longest_streak} consecutive rate limits/bot "
                "challenges. Skipping retry to protect your IP."
            ),
            priority="urgent",
        )

    # Retry pass — exceptions raised here REPLACE the first-pass exception
    # for the same job, so failures_by_kind reflects the final outcome.
    retry_exceptions: dict[tuple, BaseException] = {}
    if failed_jobs and not circuit_breaker_triggered:
        logger.info("Starting retry pass for %d failed job(s)", len(failed_jobs))
        retry_results = []
        for origin, destination, departure_date, _reason in failed_jobs:
            sleep_fn(config.FETCH_RETRY_DELAY_SECONDS)
            logger.warning("Retrying %s→%s %s", origin, destination, departure_date)
            reset_last_route_label()
            inserted, exc = execute_single_job(
                origin, destination, departure_date, db_path
            )
            route_label = _normalize_route_label(get_last_route_label())
            if exc is not None:
                logger.error(
                    "Retry failed %s→%s %s: %s",
                    origin,
                    destination,
                    departure_date,
                    exc,
                )
                retry_results.append((origin, destination, departure_date, str(exc)))
                retry_exceptions[(origin, destination, departure_date)] = exc
                failures_by_route[route_label] += 1
                failures_by_kind_so_far[_classify_failure(exc)] += 1
            elif inserted == 0:
                retry_results.append(
                    (origin, destination, departure_date, "no observations stored")
                )
                failures_by_route[route_label] += 1
                failures_by_kind_so_far["other"] += 1
            else:
                total_observations += inserted
                logger.info("Retry stored %d flights", inserted)
        failed_jobs = retry_results

    # Tally final per-category failure counts. For each job that is still in
    # failed_jobs after the retry pass, prefer the retry exception (latest
    # signal); fall back to the first-pass exception if there was no retry
    # exception (e.g. retry succeeded structurally but inserted 0 rows).
    failures_by_kind = _empty_failures_by_kind()
    for origin, destination, dep_date, _reason in failed_jobs:
        key = (origin, destination, dep_date)
        exc = retry_exceptions.get(key) or first_pass_exceptions.get(key)
        if exc is None:
            # "no observations stored" with no underlying exception — not a
            # classifiable fetch failure, count as "other".
            failures_by_kind["other"] += 1
            continue
        failures_by_kind[_classify_failure(exc)] += 1

    duration = time.monotonic() - start_time
    summary_sent = _maybe_send_failure_summary(
        failures_by_route=failures_by_route,
        failures_by_kind=failures_by_kind_so_far,
        completed_jobs=total_jobs,
        total_jobs=total_jobs,
        now=now_fn(),
        summary_sent=summary_sent,
        allow_after_run=True,
    )
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
        failures_by_kind,
    )
    check_and_alert_cheap_flights(db_path, config.PRICE_ALERT_THRESHOLD, run_date)
    return total_observations, len(failed_jobs)


def main() -> None:
    validate_config(vars(config))
    install_browser_patch()
    atexit.register(shutdown_browser)

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
