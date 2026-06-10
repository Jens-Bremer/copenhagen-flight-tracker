"""Notification helpers (ntfy) for alerts and health warnings."""

import logging
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

import config

logger = logging.getLogger(__name__)


_NTFY_TIMEOUT_SECONDS = 10
_NTFY_RETRY_COUNT = 3
_NTFY_RETRY_BACKOFF_SECONDS = 1


def send_alert(title: str, message: str, priority: str = "default") -> bool:
    """POST an alert to ntfy.sh with retry logic.

    Returns True on success, False on failure. Retries up to 3 times on transient
    errors (timeout, 5xx) with exponential backoff. Never raises.
    """
    if not config.NTFY_TOPIC:
        logger.error("NTFY_TOPIC is not set; alerts are disabled")
        return False
    url = f"{config.NTFY_URL}/{config.NTFY_TOPIC}"
    if urlparse(url).scheme != "https":
        logger.error("ntfy URL must use HTTPS: %s", url)
        return False
    title_header = title.encode("utf-8").decode("latin-1")

    for attempt in range(_NTFY_RETRY_COUNT):
        try:
            req = urllib.request.Request(
                url,
                data=message.encode("utf-8"),
                method="POST",
            )
            req.add_header("Title", title_header)
            req.add_header("Priority", priority)
            with urllib.request.urlopen(req, timeout=_NTFY_TIMEOUT_SECONDS):  # nosec B310
                logger.debug("Alert sent successfully: %s", title)
                return True
        except urllib.error.HTTPError as exc:
            if exc.code >= 500:
                logger.warning(
                    "ntfy server error (HTTP %d) on attempt %d/%d: %s",
                    exc.code,
                    attempt + 1,
                    _NTFY_RETRY_COUNT,
                    exc,
                )
                if attempt < _NTFY_RETRY_COUNT - 1:
                    time.sleep(_NTFY_RETRY_BACKOFF_SECONDS * (2**attempt))
                    continue
            else:
                logger.error(
                    "Failed to send ntfy alert (HTTP %d, non-retryable): %s",
                    exc.code,
                    exc,
                )
                return False
        except (urllib.error.URLError, TimeoutError) as exc:
            logger.warning(
                "Transient error sending ntfy alert on attempt %d/%d: %s",
                attempt + 1,
                _NTFY_RETRY_COUNT,
                exc,
            )
            if attempt < _NTFY_RETRY_COUNT - 1:
                time.sleep(_NTFY_RETRY_BACKOFF_SECONDS * (2**attempt))
                continue
        except Exception as exc:
            logger.error("Unexpected error sending ntfy alert: %s", exc)
            return False

    logger.error("Failed to send ntfy alert after %d retries", _NTFY_RETRY_COUNT)
    return False
