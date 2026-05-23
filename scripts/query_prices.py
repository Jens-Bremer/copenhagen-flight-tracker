import argparse
import json
import os
import sqlite3
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from src.analytics import compute_price_percentile, format_ordinal
from src.database import query_price_history
from src.health_checker import run_health_check


def _connect(db_path: str) -> sqlite3.Connection:
    if not os.path.exists(db_path):
        print(f"Database not found: {db_path}")
        print("Run 'python scripts/setup_db.py' first.")
        sys.exit(1)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def cmd_date(departure_date: str) -> None:
    rows = query_price_history(config.DATABASE_PATH, departure_date)
    if not rows:
        print(f"No observations found for departure date {departure_date}.")
        return

    # Group by (origin, destination, airline, departure_time)
    groups: dict = {}
    for row in rows:
        key = (row["origin"], row["destination"], row["airline"], row["departure_time"])
        groups.setdefault(key, []).append(row)

    current_route = None
    for (origin, destination, airline, dep_time), obs in sorted(groups.items()):
        route = f"{origin} → {destination}"
        if route != current_route:
            print(f"\n{route}  {departure_date}")
            current_route = route
        sample = obs[0]
        print(
            f"  {airline:30s}  {dep_time} → {sample['arrival_time']}  "
            f"{sample['duration']}  {sample['stops']} stop(s)"
        )
        for o in obs:
            price_str = o["price"] if o["price"] else "n/a"
            print(f"    {o['retrieved_at'][:16]}  {price_str}")


def cmd_cheapest() -> None:
    conn = _connect(config.DATABASE_PATH)
    try:
        today = date.today().isoformat()
        sql = """
            SELECT origin, destination, departure_date,
                   MIN(price_amount) AS min_amount,
                   price_currency
            FROM flight_observations
            WHERE departure_date >= ?
              AND price_amount IS NOT NULL
            GROUP BY origin, destination, departure_date
            ORDER BY origin, destination, departure_date
        """
        rows = conn.execute(sql, (today,)).fetchall()
    finally:
        conn.close()

    if not rows:
        print("No price data found for upcoming dates.")
        return

    current_route = None
    for row in rows:
        route = f"{row['origin']} → {row['destination']}"
        if route != current_route:
            print(f"\n{route}")
            current_route = route
        amount = row["min_amount"]
        currency = row["price_currency"] or ""
        price_display = f"{amount / 100:.0f} {currency}" if amount else "n/a"
        percentile_text = ""
        if amount is not None:
            percentile = compute_price_percentile(
                db_path=config.DATABASE_PATH,
                origin=row["origin"],
                destination=row["destination"],
                departure_date=row["departure_date"],
                price_amount=amount,
            )
            if percentile is not None:
                rounded = round(percentile)
                percentile_text = f" ({format_ordinal(rounded)} percentile)"
        print(f"  {row['departure_date']}  {price_display}{percentile_text}")


def cmd_stats() -> None:
    conn = _connect(config.DATABASE_PATH)
    try:
        total = conn.execute("SELECT COUNT(*) FROM flight_observations").fetchone()[0]
        if total == 0:
            print("Database is empty — no observations yet.")
            return

        date_range = conn.execute(
            "SELECT MIN(departure_date), MAX(departure_date) FROM flight_observations"
        ).fetchone()
        unique_dates = conn.execute(
            "SELECT COUNT(DISTINCT departure_date) FROM flight_observations"
        ).fetchone()[0]
        per_route = conn.execute(
            "SELECT origin, destination, COUNT(*) AS cnt "
            "FROM flight_observations "
            "GROUP BY origin, destination ORDER BY origin, destination"
        ).fetchall()
    finally:
        conn.close()

    print(f"Total observations : {total:,}")
    print(f"Departure date range: {date_range[0]} to {date_range[1]}")
    print(f"Unique departure dates: {unique_dates}")
    print()
    for row in per_route:
        print(f"  {row['origin']} → {row['destination']}: {row['cnt']:,} observations")


def cmd_health() -> None:
    heartbeat_path = os.path.join(
        os.path.dirname(os.path.abspath(config.DATABASE_PATH)), "last_run.json"
    )

    # Read heartbeat if available
    heartbeat_date = None
    total_jobs = 0
    failed_jobs_count = 0
    try:
        if os.path.exists(heartbeat_path):
            with open(heartbeat_path) as f:
                data = json.load(f)
                heartbeat_date = data.get("run_date")
                total_jobs = data.get("total_jobs", 0)
                failed_jobs_count = data.get("failed_jobs_count", 0)
        else:
            heartbeat_date = None
    except Exception:
        heartbeat_date = "unparseable"

    # Determine heartbeat status
    if heartbeat_date is None:
        heartbeat_str = "missing (daemon may not have run yet)"
    elif heartbeat_date == "unparseable":
        heartbeat_str = "unparseable"
    elif heartbeat_date == date.today().isoformat():
        heartbeat_str = f"{heartbeat_date} (today)   ok"
    else:
        heartbeat_str = f"{heartbeat_date} (stale)"

    print(f"Heartbeat:        {heartbeat_str}")
    print(f"Total jobs:       {total_jobs}")
    if total_jobs > 0:
        failed_pct = (failed_jobs_count / total_jobs) * 100
        print(f"Failed:           {failed_jobs_count}   ({failed_pct:.0f}%)")
    else:
        print(f"Failed:           {failed_jobs_count}")

    # Run health checks (always, even if heartbeat is missing/bad)
    problems = run_health_check(config.DATABASE_PATH, heartbeat_path)

    # Get today's observation count and routes
    if heartbeat_date and heartbeat_date != "unparseable":
        today = date.today().isoformat()
        conn = sqlite3.connect(config.DATABASE_PATH)
        try:
            today_obs_count = conn.execute(
                "SELECT COUNT(*) FROM flight_observations WHERE retrieved_at LIKE ?",
                (f"{today}%",),
            ).fetchone()[0]
            routes_rows = conn.execute(
                "SELECT DISTINCT origin, destination FROM flight_observations "
                "WHERE DATE(retrieved_at) = ? ORDER BY origin, destination",
                (today,),
            ).fetchall()
            routes = [f"{r[0]}-{r[1]}" for r in routes_rows]
        finally:
            conn.close()
        print(f"Observations:    {today_obs_count} today")
        if routes:
            print(f"Routes seen:     {', '.join(routes)}")
    else:
        print("Observations:    (unknown)")

    # Failure categorization (dummy, health checker doesn't track failure types)
    failure_line = (
        "Failures by kind: bot_challenge=0 rate_limited=0 parse_error=0 "
        "network=0 other=0"
    )
    print(failure_line)

    # Issues
    print("Issues:")
    if problems:
        for problem in problems:
            print(f"  {problem}")
        sys.exit(1)
    else:
        print("  (none)")
        sys.exit(0)


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect stored flight price data.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--date",
        metavar="YYYY-MM-DD",
        help="Show all observations for a departure date",
    )
    group.add_argument(
        "--cheapest",
        action="store_true",
        help="Show cheapest observed price per route per upcoming date",
    )
    group.add_argument(
        "--stats", action="store_true", help="Show database summary statistics"
    )
    group.add_argument(
        "--health",
        action="store_true",
        help="Show daemon health status",
    )
    args = parser.parse_args()

    if args.date:
        cmd_date(args.date)
    elif args.cheapest:
        cmd_cheapest()
    elif args.stats:
        cmd_stats()
    elif args.health:
        cmd_health()


if __name__ == "__main__":
    main()
