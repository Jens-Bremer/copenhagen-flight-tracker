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
