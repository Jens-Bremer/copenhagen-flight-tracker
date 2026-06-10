"""Expand configured routes and dates into a shuffled job list."""

import random
from datetime import date
from typing import Optional


def expand_jobs(
    routes: list[tuple[str, str]],
    dates: list[date],
    seed: Optional[int] = None,
) -> list[tuple[str, str, date]]:
    """Return the cartesian product of routes × dates, shuffled with a daily seed.

    Uses a local RNG for reproducible shuffle (deterministic job order) while
    preserving true randomness in global RNG (pacing, dwell times, proxy split).
    """
    jobs = [(origin, dest, d) for origin, dest in routes for d in dates]
    if seed is None:
        seed = date.today().toordinal()
    rng = random.Random(seed)
    rng.shuffle(jobs)
    return jobs
