"""Proxy management for flight scraping.

Loads a proxy list file (format: host:port:username:password).
The scheduler uses a single reliable proxy (no rotation) to avoid
fingerprint variation that triggers bot detection.

Usage:
    from src.proxy_manager import load_proxies

    proxies = load_proxies("data/proxies.txt")
    # proxies[0] is used for requests; single proxy is intentional
"""

import logging

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
