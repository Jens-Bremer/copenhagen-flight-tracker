"""Compute request pacing intervals to spread scraping across a daily window."""

import random
from datetime import datetime

import config


def compute_sleep_intervals(
    num_requests: int,
    window_start_hour: int,
    window_end_hour: int,
) -> list:
    """Return num_requests-1 sleep durations (in seconds) spread across the window.

    Each interval has ±10% random jitter applied.
    If the current time is inside the window, computes the remaining time.
    The minimum interval is set by config.MIN_REQUEST_INTERVAL_SECONDS.
    """
    if num_requests <= 1:
        return []

    now = datetime.now()
    window_start_dt = now.replace(
        hour=window_start_hour, minute=0, second=0, microsecond=0
    )
    window_end_dt = now.replace(hour=window_end_hour, minute=0, second=0, microsecond=0)

    if window_start_dt < now < window_end_dt:
        window_seconds = (window_end_dt - now).total_seconds()
    else:
        window_seconds = (window_end_hour - window_start_hour) * 3600

    base = window_seconds / (num_requests - 1)

    intervals = [base * random.uniform(0.9, 1.1) for _ in range(num_requests - 1)]
    return [max(float(config.MIN_REQUEST_INTERVAL_SECONDS), i) for i in intervals]


def seconds_until_window_start(window_start_hour: int) -> float:
    """Return seconds until the window opens, or 0.0 if already inside."""
    now = datetime.now()
    window_open = now.replace(hour=window_start_hour, minute=0, second=0, microsecond=0)
    if now >= window_open:
        return 0.0
    return (window_open - now).total_seconds()
