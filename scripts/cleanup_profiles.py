#!/usr/bin/env python3
"""Prune the Playwright browser-profile directory if it exceeds a configurable budget.

Old Windows home servers have limited disk; left unattended,
`data/browser_profiles/` grows indefinitely. Profiles are safe to delete —
the next scrape will recreate them (see docs/troubleshooting.md). The
scheduler invokes this weekly.

Usage:
    python scripts/cleanup_profiles.py [--profiles-dir PATH] [--max-bytes N]
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import config  # noqa: E402

logger = logging.getLogger(__name__)


def directory_size_bytes(path: Path) -> int:
    """Sum the size of every regular file under `path` (broken symlinks ignored)."""
    total = 0
    for p in path.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except (OSError, FileNotFoundError):
            continue
    return total


def cleanup_profiles(profiles_dir: Path, max_bytes: int) -> tuple[int, bool]:
    """Return (size_before, pruned?).

    Pruning removes every direct child of `profiles_dir` (each profile is a
    sub-directory). The parent itself is preserved so callers don't have to
    recreate it.
    """
    if not profiles_dir.exists():
        logger.info("cleanup_profiles: %s does not exist; nothing to do", profiles_dir)
        return 0, False

    size = directory_size_bytes(profiles_dir)
    logger.info(
        "cleanup_profiles: %s is %.1f MB (limit %.1f MB)",
        profiles_dir,
        size / 1_000_000,
        max_bytes / 1_000_000,
    )

    if size <= max_bytes:
        return size, False

    for child in profiles_dir.iterdir():
        try:
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("cleanup_profiles: could not remove %s: %s", child, exc)

    new_size = directory_size_bytes(profiles_dir)
    logger.info(
        "cleanup_profiles: pruned %s (%.1f MB → %.1f MB)",
        profiles_dir,
        size / 1_000_000,
        new_size / 1_000_000,
    )
    return size, True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profiles-dir",
        type=Path,
        default=REPO_ROOT / "data" / "browser_profiles",
    )
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=getattr(config, "BROWSER_PROFILE_MAX_BYTES", 300_000_000),
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    cleanup_profiles(args.profiles_dir, args.max_bytes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
