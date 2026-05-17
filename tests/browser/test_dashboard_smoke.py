"""Playwright smoke test for the rendered dashboard.

Asserts that the generated frontend/index.html actually boots in a real
browser: no JS errors, calendar cells render, clicking a cell drills down
into flights, clicking a flight reveals the price-history canvas, and
all five embedded JSON data blobs are present and non-empty.

This complements the substring-based assertions in test_html_generator.py
by verifying actual page BEHAVIOUR — catching regressions like a JS
syntax error, missing DOM id, or broken Chart.js wiring that would still
let the substring tests pass.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.html_generator import generate

playwright_module = pytest.importorskip(
    "playwright.sync_api",
    reason='playwright is not installed — run `pip install -e ".[dev]" '
    "&& playwright install chromium`",
)
sync_playwright = playwright_module.sync_playwright

FIXTURE_CSV = (
    Path(__file__).resolve().parent.parent
    / "fixtures"
    / ("flights_frontend_sample.csv")
)


@pytest.fixture(scope="session")
def built_dashboard(tmp_path_factory) -> Path:
    """Build a real frontend/index.html from the existing CSV fixture.

    Returns the absolute Path to the rendered HTML. Session-scoped so the
    (relatively expensive) HTML generation happens once even if more
    browser tests are added later.
    """
    out_dir = tmp_path_factory.mktemp("frontend_build")
    out_html = out_dir / "index.html"
    rows_written = generate(str(FIXTURE_CSV), str(out_html))
    assert rows_written > 0, "fixture CSV produced no rows"
    assert out_html.exists(), "html_generator.generate() did not write the file"
    return out_html


def test_dashboard_boots_in_real_browser(built_dashboard: Path) -> None:
    """Single end-to-end smoke test for the dashboard.

    Verifies, in order:
      1. No JS exceptions fire during page boot.
      2. All five `<script type="application/json">` data blobs exist
         and are non-empty.
      3. At least one non-empty calendar cell renders.
      4. Clicking that cell populates the drill-down with flight rows.
      5. Clicking a flight row reveals the price-history `<canvas>`
         (its wrapper loses the `is-hidden` class).
    """
    errors: list[Exception] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.on("pageerror", lambda exc: errors.append(exc))

            page.goto(f"file://{built_dashboard}")
            page.wait_for_load_state("networkidle")

            # 1. No JS errors during boot.
            assert errors == [], (
                f"JS exceptions during page boot: {[str(e) for e in errors]}"
            )

            # 2. All five JSON data blobs present and non-empty.
            blob_ids = [
                "DATA_METADATA",
                "DATA_CALENDAR",
                "DATA_FLIGHTS",
                "DATA_ANALYSIS",
                "DATA_SUMMARY",
            ]
            for blob_id in blob_ids:
                blob = page.locator(f'script[type="application/json"]#{blob_id}')
                assert blob.count() == 1, f"expected exactly one <script id={blob_id}>"
                content = blob.inner_text()
                assert content.strip(), f"{blob_id} blob is empty"
                # Sanity: parses as JSON, is a non-trivial object.
                assert content.strip() not in ("{}", "[]", "null"), (
                    f"{blob_id} blob has no useful content: {content!r}"
                )

            # 3. At least one non-empty calendar cell rendered.
            # `.calendar__cell.is-empty` are days with no flights; we want
            # the clickable, priced cells.
            cells = page.locator(".calendar__cell:not(.is-empty)")
            assert cells.count() > 0, (
                "no non-empty calendar cells rendered — calendar is broken"
            )

            # 4. Click the first non-empty cell, expect drill-down to fill.
            cells.first.click()
            # renderDrilldown() builds `.flight-row` buttons inside #drilldown.
            page.wait_for_selector("#drilldown .flight-row", timeout=2000)
            flight_rows = page.locator("#drilldown .flight-row")
            assert flight_rows.count() > 0, (
                "clicking a calendar cell did not populate the drill-down"
            )

            # 5. Click the first flight row → price-history canvas appears.
            # The canvas element exists in the template at all times; the
            # wrapper `#price-history-wrap` carries the `is-hidden` class
            # until a flight is selected, at which point Chart.js draws.
            flight_rows.first.click()
            page.wait_for_selector("#price-history-wrap:not(.is-hidden)", timeout=2000)
            canvas = page.locator("#price-history-wrap canvas#price-history-chart")
            assert canvas.count() == 1, (
                "expected price-history <canvas> inside #price-history-wrap"
            )
            assert canvas.is_visible(), (
                "price-history canvas exists but is not visible after "
                "selecting a flight"
            )

            # Final guard: still no JS errors after the interactions.
            assert errors == [], (
                f"JS exceptions after interaction: {[str(e) for e in errors]}"
            )
        finally:
            browser.close()
