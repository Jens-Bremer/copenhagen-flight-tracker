#!/usr/bin/env python3
"""One-off helper. Downloads Chart.js 4.4.3 from jsDelivr and stores it in
frontend/vendor/. Run once during initial setup; the file is then committed
and reused by every daily HTML generation.

Re-run only when bumping the Chart.js version. Not part of the daily pipeline.
"""
from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

CHART_JS_URL = "https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"
EXPECTED_SHA256 = "d46d97a1fd022c5fb29fa2f45ebcbc32202d73aeebf076ce5f7248f5498fc7d7"
TARGET_PATH = Path(__file__).resolve().parent.parent / "frontend" / "vendor" / "chart.min.js"


def main() -> int:
    TARGET_PATH.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {CHART_JS_URL}")
    with urllib.request.urlopen(CHART_JS_URL, timeout=30) as response:
        data = response.read()
    sha = hashlib.sha256(data).hexdigest()
    print(f"SHA-256: {sha}")
    if EXPECTED_SHA256 and sha != EXPECTED_SHA256:
        print(f"ERROR: hash mismatch (expected {EXPECTED_SHA256})", file=sys.stderr)
        return 1
    TARGET_PATH.write_bytes(data)
    print(f"Wrote {len(data):,} bytes to {TARGET_PATH}")
    print("Reminder: update EXPECTED_SHA256 in this script if this is the first run.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
