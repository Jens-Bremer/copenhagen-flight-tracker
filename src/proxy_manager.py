"""Proxy management for flight scraping.

Loads a proxy list file (format: host:port or host:port:username:password).
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

    File format: one proxy per line. Accepted formats: host:port or
    host:port:username:password (credentials ignored — Squid uses IP-based ACL).
    Lines starting with # and blank lines are skipped.

    Returns a list of proxy URLs: http://host:port

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
        if len(parts) == 2:
            host, port = parts
        elif len(parts) == 4:
            host, port = parts[0], parts[1]
            # Credentials intentionally ignored — Squid uses IP-based ACL;
            # sending creds would cause a 407 before the ACL allow rule fires.
        else:
            logger.warning(
                "Skipping malformed proxy line %d: %s "
                "(expected host:port or host:port:user:pass)",
                line_num,
                line,
            )
            continue
        logger.info("Loaded proxy %s:%s", host, port)
        proxies.append(f"http://{host}:{port}")

    logger.info("Loaded %d proxies from %s", len(proxies), path)
    return proxies
