import logging
import urllib.request

import config

logger = logging.getLogger(__name__)


_NTFY_TIMEOUT_SECONDS = 10


def send_alert(title: str, message: str, priority: str = "default") -> bool:
    """POST an alert to ntfy.sh. Returns True on success, False on failure.

    Never raises.
    """
    if not config.NTFY_TOPIC:
        return True
    url = f"{config.NTFY_URL}/{config.NTFY_TOPIC}"
    title_header = title.encode("utf-8").decode("latin-1")
    req = urllib.request.Request(
        url,
        data=message.encode("utf-8"),
        method="POST",
    )
    req.add_header("Title", title_header)
    req.add_header("Priority", priority)
    try:
        with urllib.request.urlopen(req, timeout=_NTFY_TIMEOUT_SECONDS):
            return True
    except Exception as exc:
        logger.error("Failed to send ntfy alert: %s", exc)
        return False
