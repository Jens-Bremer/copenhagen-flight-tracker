#!/usr/bin/env python3
"""CLI entry point for daily frontend HTML generation.

Reads data/flights_frontend.csv (produced by the 23:46 frontend CSV job)
and writes frontend/index.html. Chained inline from the frontend CSV
scheduler job so it runs as soon as the slim CSV is ready (no timing
race); can also be invoked manually any time. Stdlib-only; no pip deps
required at runtime.

Exit codes:
  0 — success (≥0 rows processed, output written)
  2 — input file missing
  3 — required frontend asset missing (e.g. frontend/styles.css)
  4 — uncaught exception during generation
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import config  # noqa: E402
from src.html_generator import generate  # noqa: E402
from src.log_config import setup_logging  # noqa: E402

DEFAULT_INPUT = str(
    Path(config.DATABASE_PATH).resolve().parent / "flights_frontend.csv"
)
DEFAULT_OUTPUT = str(REPO_ROOT / "frontend" / "index.html")


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    log = logging.getLogger(__name__)
    parser = argparse.ArgumentParser(description="Generate the static frontend HTML.")
    parser.add_argument("--input", default=DEFAULT_INPUT)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    try:
        n = generate(args.input, args.output)
        log.info("Wrote %s from %d rows", args.output, n)
        return 0
    except FileNotFoundError as exc:
        msg = str(exc)
        if "input file not found" in msg:
            log.error("Input CSV missing: %s", args.input)
            print(f"error: input file not found: {args.input}", file=sys.stderr)
            return 2
        log.error("Frontend asset missing: %s", exc)
        print(f"error: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:  # noqa: BLE001
        log.exception("Generation failed")
        print(f"error: {exc}", file=sys.stderr)
        return 4


if __name__ == "__main__":
    sys.exit(main())
