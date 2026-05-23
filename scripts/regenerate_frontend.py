#!/usr/bin/env python3
"""Regenerate the full frontend pipeline in one command.

Steps (in order):
  1. Export all flight_observations to data/flights_export.csv
  2. Transform to the slim data/flights_frontend.csv
  3. Render frontend/index.html + frontend/data.json

Exit codes:
  0 — all steps succeeded
  2 — input file missing at any step
  3 — required frontend asset missing (CSS/JS)
  4 — uncaught exception during generation
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import config  # noqa: E402
from scripts.export_csv import export_to_csv  # noqa: E402
from src.frontend_csv_builder import (  # noqa: E402
    BUILD_ALL_UNPARSEABLE,
    BUILD_HEADER_INVALID,
    BUILD_INPUT_MISSING,
    BUILD_OK,
    build,
)
from src.html_generator import generate  # noqa: E402
from src.log_config import setup_logging  # noqa: E402

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    parser = argparse.ArgumentParser(
        description=(
            "Regenerate the frontend pipeline: "
            "DB → export CSV → slim CSV → HTML."
        )
    )
    parser.add_argument(
        "--data-dir",
        default=str(Path(config.DATABASE_PATH).resolve().parent),
        help="Directory containing flights.db and intermediate CSVs (default: data/)",
    )
    args = parser.parse_args(argv)

    data_dir = args.data_dir
    export_csv_path = os.path.join(data_dir, "flights_export.csv")
    frontend_csv_path = os.path.join(data_dir, "flights_frontend.csv")
    html_output_path = str(REPO_ROOT / "frontend" / "index.html")

    # Step 1: Export DB → flights_export.csv
    logger.info("Step 1/3: exporting DB to %s", export_csv_path)
    try:
        row_count = export_to_csv(config.DATABASE_PATH, export_csv_path)
    except Exception as exc:
        logger.error("Export failed: %s", exc)
        print(f"error: export failed: {exc}", file=sys.stderr)
        return 4
    logger.info("Exported %d rows", row_count)

    # Step 2: Transform to slim frontend CSV
    logger.info("Step 2/3: building slim CSV → %s", frontend_csv_path)
    written, status = build(export_csv_path, frontend_csv_path)
    if status == BUILD_INPUT_MISSING:
        logger.error("Slim CSV input missing: %s", export_csv_path)
        print(f"error: input file not found: {export_csv_path}", file=sys.stderr)
        return 2
    if status in (BUILD_HEADER_INVALID, BUILD_ALL_UNPARSEABLE):
        logger.error("Slim CSV build failed (%s): %s", status, export_csv_path)
        print(
            f"error: CSV build failed ({status}): {export_csv_path}", file=sys.stderr
        )
        return 4
    logger.info("Slim CSV: wrote %d rows", written)

    # Step 3: Render HTML
    logger.info("Step 3/3: generating HTML → %s", html_output_path)
    try:
        n = generate(frontend_csv_path, html_output_path)
        logger.info("HTML generated from %d rows", n)
    except FileNotFoundError as exc:
        if "input file not found" in str(exc):
            logger.error("Frontend CSV missing: %s", frontend_csv_path)
            print(
                f"error: input file not found: {frontend_csv_path}",
                file=sys.stderr,
            )
            return 2
        logger.error("Frontend asset missing: %s", exc)
        print(f"error: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:
        logger.error("HTML generation failed: %s", exc)
        print(f"error: {exc}", file=sys.stderr)
        return 4

    logger.info("Frontend regenerated successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
