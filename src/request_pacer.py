import random
from datetime import datetime


def compute_sleep_intervals(
    num_requests: int,
    window_start_hour: int,
    window_end_hour: int,
) -> list:
    """Return num_requests-1 sleep durations (seconds) that evenly space requests across the window.

    Each interval has ±10% random jitter applied.
    If the current time is inside the window, computes the remaining time.
    The minimum interval is 120 seconds.
    """
    if num_requests <= 1:
        return []
        
    now = datetime.now()
    window_start_dt = now.replace(hour=window_start_hour, minute=0, second=0, microsecond=0)
    window_end_dt = now.replace(hour=window_end_hour, minute=0, second=0, microsecond=0)
    
    if window_start_dt < now < window_end_dt:
        window_seconds = (window_end_dt - now).total_seconds()
    else:
        window_seconds = (window_end_hour - window_start_hour) * 3600
        
    base = window_seconds / (num_requests - 1)
    
    intervals = [base * random.uniform(0.9, 1.1) for _ in range(num_requests - 1)]
    return [max(120.0, i) for i in intervals]


def seconds_until_window_start(window_start_hour: int) -> float:
    """Return seconds from now until the window opens. Returns 0.0 if already inside the window."""
    now = datetime.now()
    window_open = now.replace(hour=window_start_hour, minute=0, second=0, microsecond=0)
    if now >= window_open:
        return 0.0
    return (window_open - now).total_seconds()
