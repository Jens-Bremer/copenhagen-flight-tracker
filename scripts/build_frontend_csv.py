"""CLI entry point for the derivative frontend CSV builder.

See issue #55 / docs/superpowers/plans/2026-05-15-frontend-csv-builder.md.
Exit codes: 0 success, 2 input missing, 3 header invalid, 4 all rows
unparseable. Logging is routed through src.log_config.setup_logging() to
match the rest of the project.
"""

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.frontend_csv_builder import (
    BUILD_ALL_UNPARSEABLE,
    BUILD_HEADER_INVALID,
    BUILD_INPUT_MISSING,
    BUILD_OK,
    build,
)
from src.log_config import setup_logging

DEFAULT_INPUT = "data/flights_export.csv"
DEFAULT_OUTPUT = "data/flights_frontend.csv"

_EXIT_CODES = {
    BUILD_OK: 0,
    BUILD_INPUT_MISSING: 2,
    BUILD_HEADER_INVALID: 3,
    BUILD_ALL_UNPARSEABLE: 4,
}

logger = logging.getLogger(__name__)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build the slim, normalised data/flights_frontend.csv from "
            "data/flights_export.csv."
        ),
    )
    parser.add_argument(
        "--input",
        default=DEFAULT_INPUT,
        help=f"Input CSV path (default: {DEFAULT_INPUT})",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help=f"Output CSV path (default: {DEFAULT_OUTPUT})",
    )
    args = parser.parse_args(argv)

    setup_logging()
    written, status = build(args.input, args.output)
    if status == BUILD_OK:
        logger.info("frontend CSV: wrote %d rows to %s", written, args.output)
    return _EXIT_CODES[status]


if __name__ == "__main__":
    sys.exit(main())
