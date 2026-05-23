"""CLI entry-point for backtesting historical buy-day strategies.

Usage:
    python scripts/backtest.py [--route CPH-AMS] [--strategies 7,14,30,60]

Per CLAUDE.md, CLI scripts use plain print() rather than logging.
"""

import argparse
import sys

sys.path.insert(0, ".")

import config  # noqa: E402
from src.backtest import (  # noqa: E402
    _load_past_flights,
    run_backtest,
)


def _format_euros(cents: int) -> str:
    """Format a price in cents as a human-readable euro string.

    Args:
        cents: Price in euro-cents.

    Returns:
        String like '€54'.
    """
    return f"€{cents // 100}"


def _routes_to_check(route_arg: str | None) -> list[str]:
    """Return a list of 'ORIG-DEST' route strings to backtest.

    Args:
        route_arg: Value of the --route CLI argument, or None for all config routes.

    Returns:
        List of route strings.
    """
    if route_arg:
        return [route_arg]
    return [f"{orig}-{dest}" for orig, dest in config.ROUTES]


def main() -> None:
    """Parse arguments and print a backtest summary table for each requested route."""
    parser = argparse.ArgumentParser(
        description=(
            "Backtest historical buy-day strategies against recorded flight prices."
        )
    )
    parser.add_argument(
        "--route",
        metavar="ORIG-DEST",
        default=None,
        help="Route to analyse, e.g. CPH-AMS. Defaults to all routes in config.ROUTES.",
    )
    parser.add_argument(
        "--strategies",
        metavar="DAYS",
        default="1,3,7,14,30,60,90",
        help=(
            "Comma-separated list of days-before-departure to simulate"
            " (default: 1,3,7,14,30,60,90)."
        ),
    )
    args = parser.parse_args()

    try:
        strategy_days = [
            int(x.strip()) for x in args.strategies.split(",") if x.strip()
        ]
    except ValueError:
        print("Error: --strategies must be a comma-separated list of integers.")
        sys.exit(1)

    routes = _routes_to_check(args.route)

    for route in routes:
        stats_by_day = run_backtest(
            db_path=config.DATABASE_PATH,
            strategies=strategy_days,
            route=route,
        )

        # Count distinct past departure flights for this route.
        parts = route.split("-")
        if len(parts) == 2:
            from datetime import date

            today = date.today().isoformat()
            groups = _load_past_flights(config.DATABASE_PATH, today, route=route)
            n_past = sum(1 for obs in groups.values() if len(obs) >= 5)
        else:
            n_past = 0

        print(f"{route} (n={n_past} past departures)")

        if not stats_by_day:
            print("  (no data)")
            print()
            continue

        for days in sorted(stats_by_day):
            st = stats_by_day[days]
            # Derive average strategy price from capture_rate_mean and cheapest.
            # We don't store the average price directly; approximate from the DB.
            # Instead, just show capture rate and win rate as that's the spec.
            capture_pct = int(round(st.capture_rate_mean * 100))
            win_pct = int(round(st.win_rate_vs_naive * 100))

            # To show avg price we need to compute it separately.
            # Run a targeted query to get the per-flight strategy prices.
            avg_price_str = _avg_strategy_price_str(
                db_path=config.DATABASE_PATH,
                route=route,
                days_before=days,
            )

            print(
                f"  Buy {days:>2d} days before  {avg_price_str:<8}"
                f"  {capture_pct}% capture  "
                f"beats naive {win_pct}%"
            )

        print()


def _avg_strategy_price_str(db_path: str, route: str, days_before: int) -> str:
    """Return a formatted average euro price for a strategy across all past flights.

    Args:
        db_path: Path to the SQLite database.
        route: Route string in 'ORIG-DEST' format.
        days_before: Days before departure to simulate.

    Returns:
        Formatted string like 'avg €54', or empty string if no data.
    """
    from datetime import date

    from src.backtest import simulate_strategy_on_flight

    today = date.today().isoformat()
    groups = _load_past_flights(db_path, today, route=route)

    prices = []
    for obs in groups.values():
        if len(obs) < 5:
            continue
        price = simulate_strategy_on_flight(obs, days_before)
        if price is not None:
            prices.append(price)

    if not prices:
        return ""
    avg = sum(prices) // len(prices)
    return f"avg {_format_euros(avg)}"


if __name__ == "__main__":
    main()
