import logging
import logging.handlers
import os

import config

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"


def setup_logging(level: int = logging.INFO) -> None:
    """Configure root logger with stdout + daily-rotating file handler.

    The file handler writes to ``config.LOG_DIR/tracker.log`` and rotates at
    midnight, keeping ``config.LOG_KEEP_DAYS`` rotated copies. ``force=True``
    is passed to ``basicConfig`` so subsequent calls re-attach handlers (e.g.
    when invoked again from a test).
    """
    os.makedirs(config.LOG_DIR, exist_ok=True)
    handlers = [
        logging.StreamHandler(),
        logging.handlers.TimedRotatingFileHandler(
            filename=os.path.join(config.LOG_DIR, "tracker.log"),
            when="midnight",
            backupCount=config.LOG_KEEP_DAYS,
            encoding="utf-8",
        ),
    ]
    logging.basicConfig(
        level=level,
        format=LOG_FORMAT,
        datefmt=LOG_DATEFMT,
        handlers=handlers,
        force=True,
    )
