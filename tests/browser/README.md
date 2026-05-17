# Browser smoke tests

Playwright-driven smoke tests that boot the rendered `frontend/index.html`
in a headless Chromium and verify actual page BEHAVIOUR — not just
substring presence in the HTML.

These run separately from `pytest tests/` because they require a
~150 MB browser download.

## Run locally

```bash
pip install -e ".[dev]"
playwright install chromium
pytest tests/browser/
```

If `playwright install chromium` fails behind a corporate proxy, set
`HTTPS_PROXY` and re-run. On Linux you may also need
`playwright install-deps chromium` for system libs.

## What's covered

A single end-to-end smoke test (`test_dashboard_smoke.py`):

1. No JS exceptions fire during page boot.
2. All five `<script type="application/json">` data blobs are present
   and non-empty.
3. At least one non-empty calendar cell renders.
4. Clicking that cell populates the drill-down with flight rows.
5. Clicking a flight row reveals the price-history `<canvas>` (its
   wrapper loses the `is-hidden` class).

The HTML is built once per session from
`tests/fixtures/flights_frontend_sample.csv` via
`src.html_generator.generate(...)`.

## CI

The CI job in `.github/workflows/python-tests.yml` runs the browser
suite on Python 3.10 only — the smoke test is Python-version
independent and a single matrix entry is enough to catch regressions
without paying the browser-install cost three times.
