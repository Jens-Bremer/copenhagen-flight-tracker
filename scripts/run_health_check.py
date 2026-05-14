import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from src.health_checker import run_health_check
from src.notifier import send_alert

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

_PRIORITY_RANK = {"urgent": 4, "high": 3, "default": 2, "low": 1, "min": 0}


def _highest_priority(problems: list) -> str:
    """Extract the highest ntfy priority from a list of problem strings."""
    best = "default"
    for problem in problems:
        for level in _PRIORITY_RANK:
            if f"[{level}]" in problem and _PRIORITY_RANK[level] > _PRIORITY_RANK[best]:
                best = level
    return best


def main() -> None:
    logger.info("Running health check")
    problems = run_health_check(config.DATABASE_PATH)

    if not problems:
        logger.info("Health check passed — no problems found")
        return

    for problem in problems:
        logger.warning("Problem detected: %s", problem)

    priority = _highest_priority(problems)
    message = "\n".join(problems)
    sent = send_alert(
        title=f"Flight tracker: {len(problems)} problem(s) detected",
        message=message,
        priority=priority,
    )
    if sent:
        logger.info("Alert sent via ntfy (priority=%s)", priority)
    else:
        logger.error("Failed to send ntfy alert")


if __name__ == "__main__":
    main()
