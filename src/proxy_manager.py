"""Proxy rotation for flight scraping.

Loads a proxy list file (format: host:port:username:password)
and provides round-robin rotation. Each call to ProxyRotator.get_next() returns
the next proxy URL in the cycle.

Usage:
    from src.proxy_manager import load_proxies, ProxyRotator

    proxies = load_proxies("data/proxies.txt")
    rotator = ProxyRotator(proxies)

    proxy = rotator.get_next()  # "http://user:pass@host:port"
"""

import logging
from itertools import cycle
from typing import Optional

logger = logging.getLogger(__name__)


def load_proxies(path: str) -> list[str]:
    """Load proxies from a file.

    File format: one proxy per line as host:port:username:password
    Lines starting with # and blank lines are skipped.

    Returns a list of proxy URLs: http://username:password@host:port

    Raises:
        FileNotFoundError: if the proxy file does not exist.
    """
    with open(path) as f:
        lines = f.readlines()

    proxies: list[str] = []
    for line_num, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        parts = line.split(":")
        if len(parts) != 4:
            logger.warning(
                "Skipping malformed proxy line %d: %s (expected host:port:user:pass)",
                line_num,
                line,
            )
            continue

        host, port, username, password = parts
        proxies.append(f"http://{username}:{password}@{host}:{port}")

    logger.info("Loaded %d proxies from %s", len(proxies), path)
    return proxies


class ProxyRotator:
    """Round-robin proxy rotator.

    Not thread-safe — designed for the single-threaded scraper loop.
    Returns None from get_next() if initialized with an empty list
    (allows graceful fallback to direct connection).
    """

    def __init__(self, proxies: list[str]):
        """Create a rotator over an already-parsed list of proxy URLs."""
        self._proxies = proxies
        self._cycle = cycle(proxies) if proxies else None

    def get_next(self) -> Optional[str]:
        """Return the next proxy URL in rotation, or None if no proxies loaded."""
        if self._cycle is None:
            return None
        return next(self._cycle)

    def __len__(self) -> int:
        """Return the number of proxies in the pool."""
        return len(self._proxies)

    def __repr__(self) -> str:
        """Return a concise debug representation."""
        return f"ProxyRotator(count={len(self._proxies)})"
