# SQLite Backup Script — Design Spec

**Date:** 2026-05-15
**Issue:** #16
**Status:** Approved

## Problem

A corrupted or accidentally deleted `data/flights.db` means losing all price history. The service has no recovery path today. A daily backup with configurable retention gives a reliable fallback with no external dependencies.

## Approach

Standalone `scripts/backup_db.py` with a `backup_database()` function, registered as a fourth daily job in the scheduler at 01:00. Completely independent from the collection, health check, and CSV export jobs. Backup failures send an ntfy alert via the existing `send_alert()` mechanism.

## Files Changed

| File | Change |
|---|---|
| `scripts/backup_db.py` | New — contains `backup_database()` and a `__main__` entrypoint for manual runs (`python scripts/backup_db.py`) |
| `config.py` | Add `BACKUP_DIR` and `BACKUP_KEEP_LAST_N` |
| `src/config_validator.py` | Add validation for both new config values |
| `scripts/run_scheduler.py` | Add `_backup_job()` and register at 01:00 in `setup_schedule()` |
| `.gitignore` | Add `data/backups/` explicitly |
| `tests/test_backup_db.py` | New — unit tests for `backup_database()` |
| `tests/test_scheduler.py` | Extend — tests for `_backup_job()` and schedule registration |

## `backup_database()` Contract

```python
def backup_database(db_path: str, backup_dir: str, keep_last_n: int = 7) -> str:
```

**Steps:**
1. `os.makedirs(backup_dir, exist_ok=True)` — creates directory if absent
2. Opens source connection with `sqlite3.connect(db_path)`
3. Opens destination connection at `{backup_dir}/flights_{YYYY-MM-DD}.db`
4. Calls `src_conn.backup(dest_conn)` — stdlib, live-safe, consistent even under concurrent writes
5. Closes both connections
6. Lists all `flights_*.db` files in `backup_dir`, sorts ascending by filename (lexicographic = date order)
7. Deletes all but the last `keep_last_n` files
8. Returns the path of the newly written backup

**Invariants:**
- Running twice on the same day overwrites, not duplicates (date-based filename)
- After N runs where N > `keep_last_n`, exactly `keep_last_n` files remain
- Return value always points to a file that exists on disk

## Config Additions

```python
# config.py
BACKUP_DIR = "data/backups"
BACKUP_KEEP_LAST_N = 7
```

**Validation rules (config_validator.py):**
- `BACKUP_DIR`: non-empty string
- `BACKUP_KEEP_LAST_N`: integer ≥ 1 (not bool)

## Scheduler Integration

```python
def _backup_job() -> None:
    try:
        path = backup_database(
            config.DATABASE_PATH, config.BACKUP_DIR, config.BACKUP_KEEP_LAST_N
        )
        logger.info("Backup written to %s", path)
    except Exception as exc:
        logger.error("Backup failed: %s", exc)
        send_alert(
            title="Flight tracker: backup failed",
            message=str(exc),
            priority="high",
        )
```

- Registered at `01:00` daily — after the 22:00 scraping window, before the 06:00 window
- `try/except` keeps the daemon alive on failure, consistent with fault-tolerant philosophy
- `"high"` priority: serious (data at risk) but not `"urgent"` (no data loss has occurred yet)
- `setup_schedule()` registers 4 jobs total after this change

## Error Handling

| Scenario | Behaviour |
|---|---|
| `backup_dir` doesn't exist | Created automatically |
| DB not found | `sqlite3.connect()` raises; caught, logged, ntfy alert sent |
| Disk full | `backup()` raises; caught, logged, ntfy alert sent |
| Pruning fails | Propagates out of `backup_database()`; caught by `_backup_job()` |

## `.gitignore`

Add `data/backups/` explicitly. `data/` already covers it, but the explicit entry makes intent clear and matches the existing comment style.

## Tests

### `tests/test_backup_db.py`

All tests use `tmp_path`. No external DB required beyond `initialize_database()` for a minimal valid source.

| Test | Assertion |
|---|---|
| `test_backup_creates_file` | File exists at `{backup_dir}/flights_{today}.db` |
| `test_backup_same_day_overwrites` | Two calls on the same day → exactly 1 file |
| `test_backup_prunes_old_files` | 10 calls with `keep_last_n=7` → exactly 7 files remain |
| `test_backup_returns_path` | Return value == path of written file |

### `tests/test_scheduler.py` additions

| Test | Assertion |
|---|---|
| `test_backup_scheduled_at_0100` | `"01:00"` appears in scheduled job times |
| `test_setup_schedule_registers_four_jobs` | `len(schedule.jobs) == 4` (updates existing count test) |
| `test_backup_job_calls_backup_database` | `backup_database` called once when `_backup_job()` runs |
| `test_backup_job_sends_alert_on_failure` | `send_alert` called when `backup_database` raises |
| `test_backup_job_silent_on_success` | `send_alert` not called on success |

## Out of Scope

- Remote backup (S3, rsync) — no external dependencies by design
- Backup compression — adds complexity with marginal benefit for SQLite files of this size
- Backup verification (integrity check on the copy) — `sqlite3.backup()` guarantees consistency
