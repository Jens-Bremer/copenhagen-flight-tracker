# Contributing

## Quickstart

```bash
git clone https://github.com/Jens-Bremer/copenhagen-flight-tracker.git
cd copenhagen-flight-tracker
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
python scripts/setup_db.py
pytest tests/
```

## Local frontend loop

Run this sequence to collect a sample and preview the dashboard locally:

```bash
python scripts/run_daily.py && \
python scripts/build_frontend_csv.py && \
python scripts/generate_html.py && \
open frontend/index.html
```

On Linux use `xdg-open frontend/index.html`; on Windows use `start frontend/index.html`.

## Branch & commit conventions

Branch names follow `feat/issue-NN-short-description`, e.g. `feat/issue-131-contributing`.

Commit messages follow `<type>(#NN): subject`, e.g.:

```
feat(#87): add systemd unit, logrotate config, and aggregated skip-summary logging
fix(#110): detect cookie-consent wall and alert via ntfy
refactor(#93): split html_generator into pipeline stages
```

Accepted types: `feat`, `fix`, `refactor`, `chore`, `docs`, `test`, `style`.

Every commit must reference the issue number it belongs to.

## Code rules

The full module contract is documented in [`CLAUDE.md`](CLAUDE.md). The key constraints are:

- `src/*.py` modules import only `config`, the standard library, and their own direct pip dependencies. No cross-imports between `src/` modules, except for the allowed analytics/HTML/CSV pipeline chain (`analytics.py` → `frontend_csv_builder.py` → `html_generator.py` → `price_alerter.py`).
- Side effects (database writes, HTTP calls, sleeps) belong exclusively in `scripts/`, not in `src/`.
- Every public function must have type hints and a docstring.
- No hardcoded values — all constants must reference `config.X`.

## Tests

- **No real HTTP requests.** Mock all `fast-flights` API calls with `unittest.mock`.
- **No real database state.** Use pytest's `tmp_path` fixture to create isolated `flights.db` instances per test.
- Run the full suite before opening a PR:

  ```bash
  pytest tests/
  ```

- If you have Playwright and Chromium installed, also run the browser tests separately:

  ```bash
  pytest tests/browser/
  ```

## PR expectations

- Keep PRs small and scoped to a single issue; reference the issue number in the PR title and description.
- The branch must pass:

  ```bash
  ruff check src/ scripts/ tests/
  pytest tests/
  ```

- If your change touches the frontend pipeline (`src/frontend_csv_builder.py`, `src/html_generator.py`, `src/analytics.py`, `frontend/app.js`), update [`docs/FRONTEND.md`](docs/FRONTEND.md) to reflect any JSON contract or pipeline changes.
