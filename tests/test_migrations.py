import sqlite3

from src import migrations
from src.database import initialize_database
from src.migrations import apply_migrations


def _table_exists(db_path: str, name: str) -> bool:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def _column_names(db_path: str, table: str) -> set:
    conn = sqlite3.connect(db_path)
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    finally:
        conn.close()


def _schema_versions(db_path: str) -> list:
    conn = sqlite3.connect(db_path)
    try:
        sql = "SELECT version FROM schema_version ORDER BY version"
        return [row[0] for row in conn.execute(sql)]
    finally:
        conn.close()


# --- Test 1: empty DB + empty MIGRATIONS ---


def test_empty_migrations_returns_zero_and_creates_version_table(tmp_path, monkeypatch):
    monkeypatch.setattr(migrations, "MIGRATIONS", [])
    db_path = str(tmp_path / "flights.db")
    # Touch the file by opening a connection (no schema needed for this test).
    sqlite3.connect(db_path).close()

    applied = apply_migrations(db_path)

    assert applied == 0
    assert _table_exists(db_path, "schema_version")
    assert _schema_versions(db_path) == []


# --- Test 2: a single migration runs and is recorded ---


def test_single_migration_applies_alter_and_records_version(tmp_path, monkeypatch):
    db_path = str(tmp_path / "flights.db")
    initialize_database(db_path)

    monkeypatch.setattr(
        migrations,
        "MIGRATIONS",
        [(1, "ALTER TABLE flight_observations ADD COLUMN test_col INTEGER")],
    )

    applied = apply_migrations(db_path)

    assert applied == 1
    assert _schema_versions(db_path) == [1]
    assert "test_col" in _column_names(db_path, "flight_observations")


# --- Test 3: idempotency ---


def test_apply_migrations_is_idempotent(tmp_path, monkeypatch):
    db_path = str(tmp_path / "flights.db")
    initialize_database(db_path)

    monkeypatch.setattr(
        migrations,
        "MIGRATIONS",
        [(1, "ALTER TABLE flight_observations ADD COLUMN test_col INTEGER")],
    )

    first = apply_migrations(db_path)
    second = apply_migrations(db_path)

    assert first == 1
    assert second == 0
    assert _schema_versions(db_path) == [1]


# --- Test 4: schema_version absent until first call ---


def test_schema_version_table_created_on_first_call(tmp_path, monkeypatch):
    monkeypatch.setattr(migrations, "MIGRATIONS", [])
    db_path = str(tmp_path / "flights.db")
    # Create an empty DB file with no tables.
    sqlite3.connect(db_path).close()

    assert not _table_exists(db_path, "schema_version")

    apply_migrations(db_path)

    assert _table_exists(db_path, "schema_version")


# --- Test 5: migration #1 (duration_minutes) end-to-end (#89) ---


def test_migration_1_adds_duration_minutes_and_records_version(tmp_path):
    """Initialise a DB, run real MIGRATIONS (not monkeypatched), and assert
    that the duration_minutes column exists and schema_version contains 1.

    Note: _CREATE_TABLE already includes duration_minutes for fresh installs
    (per #89), so this test exercises an "old" schema by dropping the column
    creation first — i.e. it simulates an upgrade from a pre-migration DB by
    using a hand-rolled legacy CREATE TABLE statement.
    """
    db_path = str(tmp_path / "flights.db")
    # Hand-roll the legacy schema (pre-#89), without duration_minutes.
    legacy_sql = """
    CREATE TABLE flight_observations (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        retrieved_at        TEXT    NOT NULL,
        departure_date      TEXT    NOT NULL,
        origin              TEXT    NOT NULL,
        destination         TEXT    NOT NULL,
        airline             TEXT    NOT NULL,
        departure_time      TEXT    NOT NULL,
        arrival_time        TEXT    NOT NULL,
        duration            TEXT    NOT NULL,
        stops               INTEGER NOT NULL,
        price               TEXT,
        price_amount        INTEGER,
        price_currency      TEXT,
        is_best             INTEGER NOT NULL,
        current_price_trend TEXT
    );
    """
    conn = sqlite3.connect(db_path)
    conn.executescript(legacy_sql)
    conn.commit()
    conn.close()

    assert "duration_minutes" not in _column_names(db_path, "flight_observations")

    applied = apply_migrations(db_path)

    assert applied == 1
    assert "duration_minutes" in _column_names(db_path, "flight_observations")
    assert _schema_versions(db_path) == [1]


# --- Test 6: fresh install path is safe (#89) ---


def test_fresh_install_then_apply_migrations_is_idempotent(tmp_path):
    """``initialize_database`` creates the target schema with all columns;
    ``apply_migrations`` must not crash when migration 1's ALTER finds the
    column already present, and must still record the version so future
    migrations advance correctly."""
    db_path = str(tmp_path / "flights.db")
    initialize_database(db_path)  # fresh install, includes duration_minutes

    applied = apply_migrations(db_path)

    assert applied == 1
    assert "duration_minutes" in _column_names(db_path, "flight_observations")
    assert _schema_versions(db_path) == [1]

    # Second call must be a no-op.
    applied_again = apply_migrations(db_path)
    assert applied_again == 0
    assert _schema_versions(db_path) == [1]
