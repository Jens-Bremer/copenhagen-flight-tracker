"""Backtest module: simulate historical buy-day strategies against recorded price data.

This module is pure analytical: it reads from an existing SQLite database and
computes statistics about what would have happened if a traveller had purchased
a ticket a fixed number of days before each past departure.

Imports only stdlib + sqlite3 — no cross-imports with other src/ modules.
"""

import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional


@dataclass
class StrategyStats:
    """Aggregate statistics for a single 'buy N days before departure' strategy."""

    days_before: int
    n_flights: int
    capture_rate_mean: float  # mean of (cheapest_price / strategy_price)
    capture_rate_p10: float  # 10th-percentile of capture rates across flights
    win_rate_vs_naive: float  # fraction of flights beating naive (buy at first obs)


def simulate_strategy_on_flight(
    observations: list[dict],
    days_before: int,
    window_days: int = 2,
) -> Optional[int]:
    """Return the price (in cents) closest to *days_before* before the departure date.

    Searches within a ±window_days band around the target observation date.
    If multiple observations fall in the window, the one whose ``retrieved_at``
    date is nearest the target is chosen; ties broken by the first found.

    Args:
        observations: List of observation dicts, each containing at least
            ``departure_date`` (ISO date string), ``retrieved_at`` (ISO
            datetime string), and ``price_amount`` (int cents or None).
        days_before: How many days before departure to simulate the purchase.
        window_days: Allowed deviation in days around the target date.

    Returns:
        The ``price_amount`` in cents of the chosen observation, or None if no
        observation with a valid price falls within the window.
    """
    if not observations:
        return None

    # Determine target observation date from the first observation's departure_date.
    dep_str = observations[0]["departure_date"]
    dep_date = date.fromisoformat(dep_str)
    target_date = dep_date - timedelta(days=days_before)

    best_obs: Optional[dict] = None
    best_delta: Optional[int] = None

    for obs in observations:
        price = obs.get("price_amount")
        if price is None:
            continue
        retrieved_str = obs.get("retrieved_at", "")
        # retrieved_at may be a full ISO datetime; take the date portion.
        retrieved_date_str = retrieved_str[:10] if retrieved_str else ""
        try:
            retrieved_date = date.fromisoformat(retrieved_date_str)
        except ValueError:
            continue

        delta = abs((retrieved_date - target_date).days)
        if delta <= window_days:
            if best_delta is None or delta < best_delta:
                best_obs = obs
                best_delta = delta

    if best_obs is None:
        return None
    return best_obs["price_amount"]


def cheapest_observed(observations: list[dict]) -> Optional[int]:
    """Return the minimum ``price_amount`` (cents) across all observations.

    Args:
        observations: List of observation dicts with a ``price_amount`` key.

    Returns:
        The minimum price in cents, or None if all observations have NULL prices
        or the list is empty.
    """
    prices = [
        obs["price_amount"]
        for obs in observations
        if obs.get("price_amount") is not None
    ]
    if not prices:
        return None
    return min(prices)


def _load_past_flights(
    db_path: str,
    today: str,
    route: Optional[str] = None,
) -> dict[tuple[str, str, str], list[dict]]:
    """Load past flight observations grouped by (origin, destination, departure_date).

    Args:
        db_path: Path to the SQLite database.
        today: ISO date string for 'today'. Only flights with departure_date < today
            are included.
        route: Optional route filter in 'ORIG-DEST' format (e.g. 'CPH-AMS').

    Returns:
        Dict mapping (origin, destination, departure_date) to a list of observation
        dicts ordered by retrieved_at ascending.
    """
    sql = (
        "SELECT retrieved_at, departure_date, origin, destination, "
        "       price_amount "
        "FROM flight_observations "
        "WHERE departure_date < ?"
    )
    params: list = [today]

    if route:
        parts = route.split("-")
        if len(parts) == 2:
            sql += " AND origin = ? AND destination = ?"
            params.extend(parts)

    sql += " ORDER BY retrieved_at ASC"

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    groups: dict[tuple[str, str, str], list[dict]] = {}
    for row in rows:
        key = (row["origin"], row["destination"], row["departure_date"])
        groups.setdefault(key, []).append(dict(row))
    return groups


def _percentile(values: list[float], p: float) -> float:
    """Return the p-th percentile of *values* using linear interpolation.

    Args:
        values: Non-empty sorted list of floats.
        p: Percentile in [0, 100].

    Returns:
        Interpolated percentile value.
    """
    n = len(values)
    if n == 1:
        return values[0]
    sorted_vals = sorted(values)
    idx = (p / 100) * (n - 1)
    lo = int(idx)
    hi = lo + 1
    if hi >= n:
        return sorted_vals[-1]
    frac = idx - lo
    return sorted_vals[lo] + frac * (sorted_vals[hi] - sorted_vals[lo])


def run_backtest(
    db_path: str,
    strategies: list[int],
    route: Optional[str] = None,
    today: Optional[str] = None,
    min_obs: int = 5,
    window_days: int = 2,
) -> dict[int, StrategyStats]:
    """Run backtest simulations across all past departures.

    Groups observations by (origin, destination, departure_date). For each past
    flight with at least *min_obs* total observations, simulates purchasing at
    each strategy day-count and compares the simulated price to the cheapest
    observed price and to the naive 'buy at first observation' price.

    Args:
        db_path: Path to the SQLite database file.
        strategies: List of day-before-departure counts to simulate (e.g. [7, 14, 30]).
        route: Optional route filter in 'ORIG-DEST' format. None means all routes.
        today: ISO date string for 'today'. Defaults to the actual current date.
        min_obs: Minimum number of observations required for a flight to be included.
        window_days: Search window (±days) when locating the strategy observation.

    Returns:
        Dict mapping each strategy int to a StrategyStats instance. Strategies
        with no valid data points are omitted from the result.
    """
    if today is None:
        today = date.today().isoformat()

    groups = _load_past_flights(db_path, today, route=route)

    # Per-strategy lists of capture rates and win flags.
    capture_rates: dict[int, list[float]] = {s: [] for s in strategies}
    win_flags: dict[int, list[bool]] = {s: [] for s in strategies}

    for _key, obs in groups.items():
        if len(obs) < min_obs:
            continue

        best = cheapest_observed(obs)
        if best is None or best == 0:
            continue

        # Naive price: price_amount of the earliest observation with a price.
        naive_price: Optional[int] = None
        for o in obs:
            if o.get("price_amount") is not None:
                naive_price = o["price_amount"]
                break

        for s in strategies:
            strategy_price = simulate_strategy_on_flight(
                obs, s, window_days=window_days
            )
            if strategy_price is None or strategy_price == 0:
                continue
            capture = best / strategy_price
            capture_rates[s].append(capture)
            if naive_price is not None and naive_price != 0:
                beats_naive = strategy_price < naive_price
                win_flags[s].append(beats_naive)

    result: dict[int, StrategyStats] = {}
    for s in strategies:
        rates = capture_rates[s]
        if not rates:
            continue
        wins = win_flags[s]
        result[s] = StrategyStats(
            days_before=s,
            n_flights=len(rates),
            capture_rate_mean=sum(rates) / len(rates),
            capture_rate_p10=_percentile(rates, 10),
            win_rate_vs_naive=(sum(wins) / len(wins)) if wins else 0.0,
        )
    return result
