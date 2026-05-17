"""Minimal version-tracked SQLite migration framework.

Schema changes are recorded as ordered ``(version, sql)`` tuples in the
module-level :data:`MIGRATIONS` list. A ``schema_version`` table inside the
same SQLite database tracks the highest applied version (no sidecar file).

On each call to :func:`apply_migrations`, the current version is read as
``MAX(version)`` from ``schema_version`` (default ``0`` when the table is
empty). Every migration whose version is strictly greater than the current
one is executed in order; each migration's SQL and the matching
``INSERT INTO schema_version`` row are committed together so a crash
mid-upgrade leaves the database at a known boundary.

Design rules:
- Stdlib only (``sqlite3``). No Alembic, no third-party framework.
- Append-only: never edit or remove an existing migration tuple; add a new
  higher-numbered tuple instead.
- Version numbers are integers and must be strictly increasing. Gaps are
  allowed but discouraged.
- Migrations should be idempotent where practical, but the framework only
  guarantees they run once per database.
"""

import sqlite3

MIGRATIONS: list[tuple[int, str]] = [
    (1, "ALTER TABLE flight_observations ADD COLUMN duration_minutes INTEGER"),
]


def apply_migrations(db_path: str) -> int:
    """Apply all pending migrations to the SQLite database at ``db_path``.

    Creates the ``schema_version`` tracking table if missing, then runs every
    migration in :data:`MIGRATIONS` whose version is greater than the highest
    currently recorded version. Each migration runs in its own transaction
    (SQL + ``INSERT INTO schema_version`` + ``commit``) so an interrupted
    upgrade leaves the database at a clean version boundary.

    Args:
        db_path: Filesystem path to the SQLite database file.

    Returns:
        The number of migrations applied during this call.
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)"
        )
        conn.commit()

        row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
        current = row[0] if row and row[0] is not None else 0

        applied = 0
        for version, sql in MIGRATIONS:
            if version <= current:
                continue
            try:
                conn.executescript(sql)
            except sqlite3.OperationalError as exc:
                # Fresh installs apply the full target schema via
                # ``initialize_database``; subsequent ``apply_migrations``
                # would otherwise fail on ``ALTER TABLE ... ADD COLUMN`` for
                # a column that already exists. Treat that specific case as
                # "already applied" and still record the version so the
                # boundary advances. Any other OperationalError re-raises.
                if "duplicate column name" not in str(exc):
                    raise
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
            conn.commit()
            applied += 1
        return applied
    finally:
        conn.close()
