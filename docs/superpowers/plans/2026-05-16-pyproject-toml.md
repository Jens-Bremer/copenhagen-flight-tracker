# pyproject.toml Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `pyproject.toml` with ruff and pytest config so `ruff check .` and `pytest` both pass cleanly.

**Architecture:** A single new file (`pyproject.toml`) declares project metadata plus `[tool.ruff]`, `[tool.ruff.lint]`, and `[tool.pytest.ini_options]` sections. Existing source and test files are updated to satisfy the newly-enforced rules — import sorting (I001), deprecated typing imports (UP035), non-PEP-585 annotations (UP006), line length (E501), and unused loop variables (B007). No runtime logic changes.

**Tech Stack:** ruff 0.15+, pytest 8+, Python 3.9.6 (target-version = py39)

---

### Task 1: Create branch

- [ ] **Step 1: Create and switch to feature branch**

```bash
git checkout -b feat/issue-91-pyproject-toml
```

Expected: Switched to a new branch 'feat/issue-91-pyproject-toml'

---

### Task 2: Add pyproject.toml

**Files:**
- Create: `pyproject.toml`

- [ ] **Step 1: Write the file**

```toml
[project]
name = "copenhagen-flight-tracker"
version = "0.1.0"
description = "Self-hosted flight price tracker for CPH-AMS routes"
requires-python = ">=3.9"

[tool.ruff]
line-length = 88
target-version = "py39"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Verify ruff picks up the config**

```bash
ruff check . --statistics 2>&1 | tail -5
```

Expected: shows 56 errors (not 0 — that's fixed in later tasks).

---

### Task 3: Auto-fix import sorting (I001)

**Files:** multiple source and test files (ruff rewrites in-place)

- [ ] **Step 1: Apply safe auto-fixes**

```bash
ruff check . --fix
```

Expected: `Found 41 errors (15 fixed, 41 remaining).`
All I001 violations are gone; E501, B007, UP006, UP035 remain.

---

### Task 4: Apply unsafe auto-fixes (UP006, UP035)

**Files:** files using `List[…]`, `Dict[…]`, `Tuple[…]` from `typing`, and deprecated `typing.Callable` / `typing.TimeoutError`

- [ ] **Step 1: Apply unsafe fixes**

```bash
ruff check . --unsafe-fixes --fix
```

Expected: UP006 and UP035 violations removed. Remaining violations: 33 E501 + 2 B007 = 35 errors.

- [ ] **Step 2: Confirm remaining count**

```bash
ruff check . --statistics
```

Expected:
```
33  E501  [ ] line-too-long
 2  B007  [ ] unused-loop-control-variable
Found 35 errors.
```

---

### Task 5: Fix B007 — unused loop variables

**Files:**
- Modify: `tests/test_html_generator.py:342-343`

- [ ] **Step 1: Rename unused loop variables**

At `tests/test_html_generator.py:342`:
```python
# Before
for route, blob in summary.items():
    for airline, bins in blob["histogram"].items():
# After
for _route, blob in summary.items():
    for _airline, bins in blob["histogram"].items():
```

- [ ] **Step 2: Verify B007 is gone**

```bash
ruff check tests/test_html_generator.py --select B007
```

Expected: `All checks passed!`

---

### Task 6: Fix E501 — line-too-long (scripts/)

**Files:**
- Modify: `scripts/query_prices.py:114`
- Modify: `scripts/run_daily.py:56`
- Modify: `scripts/run_scheduler.py:137,179`

- [ ] **Step 1: Fix `scripts/query_prices.py:114`**

```python
# Before (line 113-114):
            "SELECT origin, destination, COUNT(*) AS cnt "
            "FROM flight_observations GROUP BY origin, destination ORDER BY origin, destination"
# After:
            "SELECT origin, destination, COUNT(*) AS cnt "
            "FROM flight_observations "
            "GROUP BY origin, destination ORDER BY origin, destination"
```

- [ ] **Step 2: Fix `scripts/run_daily.py:56`**

```python
# Before:
    """Execute one full collection cycle. Returns (total_observations, failed_jobs_count)."""
# After:
    """Execute one full collection cycle.

    Returns (total_observations, failed_jobs_count).
    """
```

- [ ] **Step 3: Fix `scripts/run_scheduler.py:137`**

```python
# Before:
    """Run the health check and alert if problems found. Called by the scheduler at 23:30."""
# After:
    """Run the health check and alert if problems found.

    Called by the scheduler at 23:30.
    """
```

- [ ] **Step 4: Fix `scripts/run_scheduler.py:179`**

```python
# Before:
            "Started within the operating window. Executing immediate collection with compressed intervals."
# After:
            "Started within the operating window. "
            "Executing immediate collection with compressed intervals."
```

- [ ] **Step 5: Verify scripts clean**

```bash
ruff check scripts/ --select E501
```

Expected: `All checks passed!`

---

### Task 7: Fix E501 — line-too-long (src/)

**Files:**
- Modify: `src/config_validator.py:2,74,116`
- Modify: `src/database.py:56`
- Modify: `src/date_generator.py:9`
- Modify: `src/health_checker.py:21,40,95,110,117,124,131,140,155,164,178,186`
- Modify: `src/html_generator.py:232`
- Modify: `src/log_config.py:8`
- Modify: `src/notifier.py:13`
- Modify: `src/price_alerter.py:29,85,95`
- Modify: `src/request_pacer.py:12,39`

- [ ] **Step 1: Fix `src/config_validator.py:2`**

```python
# Before:
    """Validate all tuneable config values. Raises ValueError with a clear message on any problem."""
# After:
    """Validate all tuneable config values.

    Raises ValueError with a clear message on any problem.
    """
```

- [ ] **Step 2: Fix `src/config_validator.py:74`**

```python
# Before:
            f"DAILY_WINDOW_START_HOUR ({start}) must be less than DAILY_WINDOW_END_HOUR ({end})"
# After:
            f"DAILY_WINDOW_START_HOUR ({start}) must be less than "
            f"DAILY_WINDOW_END_HOUR ({end})"
```

- [ ] **Step 3: Fix `src/config_validator.py:116`**

```python
# Before:
                "PRICE_ALERT_THRESHOLD dict must include a '_default' key as a fallback threshold"
# After:
                "PRICE_ALERT_THRESHOLD dict must include a '_default' key "
                "as a fallback threshold"
```

- [ ] **Step 4: Fix `src/database.py:56`**

```python
# Before:
    """Insert a batch of observation dicts in a single transaction. Returns row count inserted."""
# After:
    """Insert a batch of observation dicts in a single transaction.

    Returns row count inserted.
    """
```

- [ ] **Step 5: Fix `src/date_generator.py:9`**

```python
# Before:
    """Return sorted list of dates from today through MAX_MONTHS_AHEAD that fall on DEPARTURE_WEEKDAYS."""
# After:
    """Return sorted list of dates from today through MAX_MONTHS_AHEAD that fall on DEPARTURE_WEEKDAYS.
    """
```

Wait — that's still long. Correct fix:
```python
    """Return dates from today through MAX_MONTHS_AHEAD that fall on DEPARTURE_WEEKDAYS, sorted."""
```

- [ ] **Step 6: Fix `src/health_checker.py:21`**

```python
# Before (full line):
            return f"[urgent] Heartbeat stale: last run was {data.get('run_date')}, expected {date.today().isoformat()}"
# After:
            return (
                f"[urgent] Heartbeat stale: last run was {data.get('run_date')}, "
                f"expected {date.today().isoformat()}"
            )
```

- [ ] **Step 7: Fix `src/health_checker.py:40`**

```python
# Before:
            return f"[high] High failure rate: {failed}/{total_jobs} jobs failed ({failed / total_jobs:.0%})"
# After:
            return (
                f"[high] High failure rate: {failed}/{total_jobs} jobs failed "
                f"({failed / total_jobs:.0%})"
            )
```

- [ ] **Step 8: Fix `src/health_checker.py:95,110,117`**

Line 95 (`_check_currency_inconsistency` docstring, 93 chars):
```python
# Before:
    """Return a problem string if more than one currency was seen in today's observations."""
# After:
    """Return a problem string if more than one currency was seen today."""
```

Line 110 (`f"[default] Currency inconsistency..."`, 93 chars):
```python
# Before:
        return f"[default] Currency inconsistency: multiple currencies found today ({found})"
# After:
        return (
            f"[default] Currency inconsistency: multiple currencies found today ({found})"
        )
```

Wait — the line with the parens is the same length. Better:
```python
        return f"[default] Currency inconsistency: multiple currencies today ({found})"
```

Line 117 (`check_missing_routes` docstring, 93 chars):
```python
# Before:
    """Return a problem string for each expected route with zero observations on run_date."""
# After:
    """Return a problem string for each expected route with no observations on run_date."""
```

- [ ] **Step 9: Fix `src/health_checker.py:124`**

```python
# Before (line 124):
            "SELECT DISTINCT origin, destination FROM flight_observations WHERE DATE(retrieved_at) = ?",
# After:
            "SELECT DISTINCT origin, destination "
            "FROM flight_observations WHERE DATE(retrieved_at) = ?",
```

- [ ] **Step 10: Fix `src/health_checker.py:131`**

```python
# Before (89 chars — just 1 over):
        f"[high] Missing route: no observations for {origin}→{destination} on {run_date}"
# After:
        f"[high] Missing route: no observations for {origin}→{destination} on {run_date}"  # noqa: E501
```

Wait — noqa suppression is an option. Or shorten the message:
```python
        f"[high] Missing route: {origin}→{destination} had no observations on {run_date}"
```

- [ ] **Step 11: Fix `src/health_checker.py:140`**

```python
# Before (check_price_variance docstring, 113 chars):
    """Return a problem string for each route with fewer than min_distinct_prices distinct prices on run_date."""
# After:
    """Return a problem string for each route with fewer than min_distinct_prices distinct prices."""
```

- [ ] **Step 12: Fix `src/health_checker.py:155`**

```python
# Before (f-string, 105 chars):
        f"[high] Price variance: only {count} distinct price(s) for {origin}→{destination} on {run_date}"
# After:
        f"[high] Price variance: only {count} distinct price(s) "
        f"for {origin}→{destination} on {run_date}"
```

- [ ] **Step 13: Fix `src/health_checker.py:164`**

```python
# Before (check_observation_count docstring, 91 chars):
    """Return a problem string if total observations for run_date is below expected_min."""
# After:
    """Return a problem string if total observations on run_date are below expected_min."""
```

- [ ] **Step 14: Fix `src/health_checker.py:178`**

```python
# Before (f-string, 114 chars):
            f"[high] Low observation count: {count} observations on {run_date} (expected at least {expected_min})"
# After:
            f"[high] Low observation count: {count} observations on {run_date} "
            f"(expected at least {expected_min})"
```

- [ ] **Step 15: Fix `src/health_checker.py:186`**

```python
# Before (run_health_check docstring, 92 chars):
    """Run all health checks and return a list of problem descriptions (empty = healthy)."""
# After:
    """Run all health checks and return a list of problem descriptions.

    An empty list means healthy.
    """
```

- [ ] **Step 16: Fix `src/html_generator.py:232`**

```python
# Before (comment, 98 chars):
    # Group prices by (route, dep_date, airline, dep_time, days_before) for normalised progression
# After:
    # Group prices by (route, dep_date, airline, dep_time, days_before) for normalised
    # price progression
```

- [ ] **Step 17: Fix `src/log_config.py:8`**

```python
# Before:
    """Configure root logger. Safe to call multiple times — basicConfig is a no-op if already set."""
# After:
    """Configure root logger. Safe to call multiple times — basicConfig is a no-op if already set.
    """
```

Wait still long. Better:
```python
    """Configure root logger. Safe to call multiple times (basicConfig no-ops if already set)."""
```

- [ ] **Step 18: Fix `src/notifier.py:13`**

```python
# Before:
    """POST an alert to ntfy.sh. Returns True on success, False on failure. Never raises."""
# After:
    """POST an alert to ntfy.sh. Returns True on success, False on failure. Never raises.
    """
```

Still 91 chars on line 1. Better:
```python
    """POST an alert to ntfy.sh. Returns True on success, False on failure. Never raises."""
```

Count: `    """POST an alert to ntfy.sh. Returns True on success, False on failure. Never raises."""`
= 4 + 3 + 80 + 3 = ... let me count manually:
`    """POST an alert to ntfy.sh. Returns True on success, False on failure. Never raises."""`
That's 92 chars. Fix:
```python
    """POST an alert to ntfy.sh. Returns True on success, False on failure.

    Never raises.
    """
```

- [ ] **Step 19: Fix `src/price_alerter.py:29`**

```python
# Before:
    """Return today's observed flights where price_amount <= threshold (per-route if dict), ordered by price."""
# After:
    """Return flights where price_amount <= threshold (per-route if dict), ordered by price."""
```

- [ ] **Step 20: Fix `src/price_alerter.py:85,95`**

Line 85 (f-string, 92 chars):
```python
# Before:
            f"  {f['origin']}→{f['destination']}  {f['departure_date']}"
            f"  {f['airline']}  {f['departure_time']}  {amount} {currency}{percentile_text}"
# After (line 85 is the second string starting with f"  {f['airline']}"):
```

Wait, let me re-read. The violation is at line 85. Let me check what line 85 is exactly.

Actually I read lines 83-86 earlier:
```
83:        lines.append(
84:            f"  {f['origin']}→{f['destination']}  {f['departure_date']}"
85:            f"  {f['airline']}  {f['departure_time']}  {amount} {currency}{percentile_text}"
86:        )
```

Line 85 is 92 chars. This is hard to shorten without changing output. I could split differently:
```python
        lines.append(
            f"  {f['origin']}→{f['destination']}  {f['departure_date']}"
            f"  {f['airline']}  {f['departure_time']}"
            f"  {amount} {currency}{percentile_text}"
        )
```

Line 95 (`check_and_alert_cheap_flights` docstring, 92 chars):
```python
# Before:
    """Find cheap flights and send an alert if any exist. Returns True if alert was sent."""
# After:
    """Find cheap flights and send an alert if any exist.

    Returns True if alert was sent.
    """
```

- [ ] **Step 21: Fix `src/request_pacer.py:12,39`**

Line 12 (first docstring line, 100 chars):
```python
# Before:
    """Return num_requests-1 sleep durations (seconds) that evenly space requests across the window.
# After — the line is the start of a multiline docstring, just wrap it:
    """Return num_requests-1 sleep durations (seconds) that space requests across the window.
```

Line 39 (docstring, 99 chars):
```python
# Before:
    """Return seconds from now until the window opens. Returns 0.0 if already inside the window."""
# After:
    """Return seconds from now until the window opens. Returns 0.0 if already in the window."""
```

- [ ] **Step 22: Verify src/ is clean**

```bash
ruff check src/ --select E501
```

Expected: `All checks passed!`

---

### Task 8: Fix E501 — line-too-long (tests/)

**Files:**
- Modify: `tests/test_frontend_csv_builder.py:604`
- Modify: `tests/test_integration.py:112,141`
- Modify: `tests/test_request_pacer.py:32`

- [ ] **Step 1: Fix `tests/test_frontend_csv_builder.py:604`**

```python
# Before:
    """Modest scale (1k rows) — full perf is left to manual runs against the live file."""
# After:
    """Modest scale (1k rows) — full perf is left to manual runs against the live file.
    """
```

Wait 90 chars. Better:
```python
    """Modest scale (1k rows) — full perf left to manual runs against the live file."""
```

- [ ] **Step 2: Fix `tests/test_integration.py:112`**

```python
# Before:
    """A job that raises in pass 1 but returns results in pass 2 is counted as success."""
# After:
    """A job that raises in pass 1 but returns results in pass 2 is counted as success.
    """
```

90 chars. Fix:
```python
    """A job that raises in pass 1 but succeeds in pass 2 is counted as success."""
```

- [ ] **Step 3: Fix `tests/test_integration.py:141`**

Need to see line 141. Let me read it.

- [ ] **Step 4: Fix `tests/test_request_pacer.py:32`**

```python
# Before (comment, 89 chars):
    # With jitter removed (seed for reproducibility), intervals should cluster near base.
# After:
    # With jitter removed (reproducible seed), intervals should cluster near base.
```

- [ ] **Step 5: Verify tests/ is clean**

```bash
ruff check tests/ --select E501
```

Expected: `All checks passed!`

---

### Task 9: Full ruff verification

- [ ] **Step 1: Run ruff across entire codebase**

```bash
ruff check .
```

Expected: `All checks passed!`

---

### Task 10: Run pytest

- [ ] **Step 1: Run full test suite**

```bash
pytest
```

Expected: All 333 tests pass, 0 failures.

---

### Task 11: Commit and push PR

- [ ] **Step 1: Stage all changes**

```bash
git add pyproject.toml scripts/ src/ tests/
```

- [ ] **Step 2: Commit**

```bash
git commit -m "tooling(#91): add pyproject.toml with ruff and pytest config

- Add [project], [tool.ruff], [tool.ruff.lint], [tool.pytest.ini_options]
- target-version = py39 (matches actual runtime)
- Fix all 56 ruff violations: import sorting, deprecated typing, E501, B007"
```

- [ ] **Step 3: Push and open PR**

```bash
git push -u origin feat/issue-91-pyproject-toml
gh pr create --title "tooling(#91): add pyproject.toml" \
  --body "Closes #91"
```
