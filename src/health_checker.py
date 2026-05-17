import json
import logging
import os
import sqlite3
from datetime import date, timedelta
from typing import Optional

import config

logger = logging.getLogger(__name__)


def _check_heartbeat_stale(heartbeat_path: str) -> Optional[str]:
    """Return a problem string if the heartbeat file is missing, unparseable,
    or not from today.

    Operators need to distinguish three failure modes:
    (a) file missing — daemon never wrote it (crashed before completion, or
        not running at all),
    (b) file present but unparseable — almost certainly a mid-write crash
        before the atomic-rename fix landed, or disk corruption,
    (c) file from a prior date — daemon ran on an earlier day but not today.
    """
    today = date.today().isoformat()
    if not os.path.exists(heartbeat_path):
        return (
            f"[urgent] Heartbeat missing: {heartbeat_path} does not exist "
            f"(daemon may not have run today, expected {today})"
        )
    try:
        with open(heartbeat_path) as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        return (
            f"[urgent] Heartbeat unparseable: {heartbeat_path} is not valid "
            f"JSON ({exc}); likely a mid-write crash or disk corruption"
        )
    except Exception as exc:
        return (
            f"[urgent] Heartbeat unreadable: could not open {heartbeat_path} "
            f"({exc})"
        )
    run_date = data.get("run_date")
    if run_date != today:
        return (
            f"[urgent] Heartbeat outdated: last run was {run_date}, "
            f"expected {today} (daemon did not complete a run today)"
        )
    return None


def _check_high_failure_rate(heartbeat_path: str) -> Optional[str]:
    """Return a problem string if failed jobs exceed configured threshold."""
    if not os.path.exists(heartbeat_path):
        return None
    try:
        with open(heartbeat_path) as f:
            data = json.load(f)
        total_jobs = data.get("total_jobs", 0)
        failed = data.get("failed_jobs_count", 0)
        if (
            total_jobs > 0
            and failed / total_jobs > config.HEALTH_FAILURE_RATE_THRESHOLD
        ):
            return (
                f"[high] High failure rate: {failed}/{total_jobs} jobs failed "
                f"({failed / total_jobs:.0%})"
            )
    except Exception as exc:
        logger.warning(
            "Could not read heartbeat for failure-rate check: %s", exc
        )
        return None
    return None


def _check_bot_challenge_today(heartbeat_path: str) -> Optional[str]:
    """Return a problem string if today's heartbeat shows bot-challenge hits.

    A non-zero bot_challenge count is the project's LEADING ban indicator —
    Google has started serving consent/captcha pages where it used to serve
    real flight data. The right response is almost always to refresh the
    SOCS=CAI cookie strategy (see #110/#111), not to wait it out.
    """
    if not os.path.exists(heartbeat_path):
        return None
    try:
        with open(heartbeat_path) as f:
            data = json.load(f)
    except Exception as exc:
        logger.warning(
            "Could not read heartbeat for bot-challenge check: %s", exc
        )
        return None
    failures = data.get("failures_by_kind") or {}
    count = failures.get("bot_challenge", 0)
    if count and count > 0:
        return (
            f"[urgent] Bot challenge today: {count} response(s) flagged as "
            f"challenge pages — cookie consent may have rotated; see #110/#111"
        )
    return None


def _check_consecutive_failures_per_route(db_path: str) -> list[str]:
    """Per-route problem if a route has N+ consecutive empty days.

    Walks back from yesterday (today is in-progress and may legitimately have
    no rows yet at health-check time). Threshold is config.CONSECUTIVE_FAILURE_DAYS.

    Routes that have never been observed are silently skipped — a brand-new
    route on day 1 is not a "failure". Only routes with at least one historical
    observation can trip this check, which makes it a true regression signal.

    Routes that already have observations TODAY are also silently skipped:
    the daily collection has clearly succeeded for that route, so the streak
    is zero regardless of intermediate gaps.
    """
    today = date.today()
    yesterday = today - timedelta(days=1)
    problems: list[str] = []
    conn = sqlite3.connect(db_path)
    try:
        for origin, destination in config.ROUTES:
            # Skip routes the system has never seen — first day of a route
            # is not a failure mode.
            route_total = conn.execute(
                "SELECT COUNT(*) FROM flight_observations "
                "WHERE origin = ? AND destination = ?",
                (origin, destination),
            ).fetchone()[0]
            if route_total == 0:
                continue
            # Today's collection already succeeded for this route → streak 0.
            today_count = conn.execute(
                "SELECT COUNT(*) FROM flight_observations "
                "WHERE origin = ? AND destination = ? "
                "AND DATE(retrieved_at) = ?",
                (origin, destination, today.isoformat()),
            ).fetchone()[0]
            if today_count > 0:
                continue
            streak = 0
            cursor = yesterday
            while True:
                count = conn.execute(
                    "SELECT COUNT(*) FROM flight_observations "
                    "WHERE origin = ? AND destination = ? "
                    "AND DATE(retrieved_at) = ?",
                    (origin, destination, cursor.isoformat()),
                ).fetchone()[0]
                if count > 0:
                    break
                streak += 1
                cursor -= timedelta(days=1)
                # Cap the walk-back so an old-but-now-dead route can't loop
                # back to the dawn of time.
                if streak > 365:
                    break
            if streak >= config.CONSECUTIVE_FAILURE_DAYS:
                problems.append(
                    f"[high] No observations for {origin}→{destination} "
                    f"for {streak} consecutive days"
                )
    finally:
        conn.close()
    return problems


def _check_zero_observations_today(db_path: str) -> Optional[str]:
    """Return a problem string if no observations were retrieved today."""
    today = date.today().isoformat()
    conn = sqlite3.connect(db_path)
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM flight_observations WHERE retrieved_at LIKE ?",
            (f"{today}%",),
        ).fetchone()[0]
    finally:
        conn.close()
    if count == 0:
        return "[urgent] Zero observations today: no rows retrieved on " + today
    return None


def _check_observation_count_drop(db_path: str) -> Optional[str]:
    """Return a problem string if today's count is below configured 7-day threshold."""
    today = date.today().isoformat()
    conn = sqlite3.connect(db_path)
    try:
        today_count = conn.execute(
            "SELECT COUNT(*) FROM flight_observations WHERE retrieved_at LIKE ?",
            (f"{today}%",),
        ).fetchone()[0]
        avg_row = conn.execute(
            """
            SELECT AVG(daily_count) FROM (
                SELECT DATE(retrieved_at) AS day, COUNT(*) AS daily_count
                FROM flight_observations
                WHERE DATE(retrieved_at) < ?
                GROUP BY day
                ORDER BY day DESC
                LIMIT 7
            )
            """,
            (today,),
        ).fetchone()
    finally:
        conn.close()
    avg = avg_row[0]
    if avg and today_count < avg * config.HEALTH_COUNT_DROP_THRESHOLD:
        return (
            f"[high] Observation count drop: today={today_count}, 7-day avg={avg:.0f}"
        )
    return None


def _check_currency_inconsistency(db_path: str) -> Optional[str]:
    """Return a problem string if more than one currency was seen today."""
    today = date.today().isoformat()
    conn = sqlite3.connect(db_path)
    try:
        currencies = conn.execute(
            """
            SELECT DISTINCT price_currency FROM flight_observations
            WHERE retrieved_at LIKE ? AND price_currency IS NOT NULL
            """,
            (f"{today}%",),
        ).fetchall()
    finally:
        conn.close()
    if len(currencies) > 1:
        found = ", ".join(r[0] for r in currencies)
        return f"[default] Currency inconsistency: multiple currencies today ({found})"
    return None


def check_missing_routes(
    db_path: str, run_date: str, expected_routes: list
) -> list[str]:
    """Return a problem string per route missing observations on run_date."""
    conn = sqlite3.connect(db_path)
    try:
        total = conn.execute("SELECT COUNT(*) FROM flight_observations").fetchone()[0]
        if total == 0:
            return []
        rows = conn.execute(
            "SELECT DISTINCT origin, destination "
            "FROM flight_observations WHERE DATE(retrieved_at) = ?",
            (run_date,),
        ).fetchall()
    finally:
        conn.close()
    present = {(r[0], r[1]) for r in rows}
    return [
        f"[high] Missing route: {origin}→{destination} not observed on {run_date}"
        for origin, destination in expected_routes
        if (origin, destination) not in present
    ]


def check_price_variance(
    db_path: str, run_date: str, min_distinct_prices: int = 3
) -> list[str]:
    """Per-route problem string if distinct prices < min_distinct_prices on run_date."""
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT origin, destination, COUNT(DISTINCT price_amount) AS distinct_prices
            FROM flight_observations
            WHERE DATE(retrieved_at) = ?
            GROUP BY origin, destination
            """,
            (run_date,),
        ).fetchall()
    finally:
        conn.close()
    return [
        f"[high] Price variance: only {count} distinct price(s) "
        f"for {origin}→{destination} on {run_date}"
        for origin, destination, count in rows
        if count < min_distinct_prices
    ]


def check_observation_count(
    db_path: str, run_date: str, expected_min: int
) -> list[str]:
    """Return a problem string if observations on run_date are below expected_min."""
    conn = sqlite3.connect(db_path)
    try:
        total = conn.execute("SELECT COUNT(*) FROM flight_observations").fetchone()[0]
        if total == 0:
            return []
        count = conn.execute(
            "SELECT COUNT(*) FROM flight_observations WHERE DATE(retrieved_at) = ?",
            (run_date,),
        ).fetchone()[0]
    finally:
        conn.close()
    if count < expected_min:
        return [
            f"[high] Low observation count: {count} observations on {run_date} "
            f"(expected at least {expected_min})"
        ]
    return []


def run_health_check(
    db_path: str, heartbeat_path: Optional[str] = None, run_date: Optional[str] = None
) -> list:
    """Run all health checks and return a list of problem descriptions.

    An empty list means healthy.
    """
    if heartbeat_path is None:
        heartbeat_path = os.path.join(
            os.path.dirname(os.path.abspath(db_path)), "last_run.json"
        )
    if run_date is None:
        run_date = date.today().isoformat()
    single_checks = [
        _check_heartbeat_stale(heartbeat_path),
        _check_high_failure_rate(heartbeat_path),
        _check_bot_challenge_today(heartbeat_path),
        _check_zero_observations_today(db_path),
        _check_observation_count_drop(db_path),
        _check_currency_inconsistency(db_path),
    ]
    problems = [c for c in single_checks if c is not None]
    problems.extend(check_missing_routes(db_path, run_date, config.ROUTES))
    problems.extend(check_price_variance(db_path, run_date))
    problems.extend(_check_consecutive_failures_per_route(db_path))
    for p in problems:
        logger.warning("Health check problem: %s", p)
    return problems
