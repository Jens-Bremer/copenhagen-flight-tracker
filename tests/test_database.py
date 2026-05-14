import sqlite3

import pytest

from src.database import initialize_database, insert_observations, query_price_history


SAMPLE = {
    "retrieved_at": "2025-09-05T06:00:00+00:00",
    "departure_date": "2025-09-05",
    "origin": "CPH",
    "destination": "AMS",
    "airline": "SAS",
    "departure_time": "08:00",
    "arrival_time": "10:05",
    "duration": "2h 5m",
    "stops": 0,
    "price": "€89",
    "price_amount": 8900,
    "price_currency": "EUR",
    "is_best": True,
    "current_price_trend": "typical",
}


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "flights.db")
    initialize_database(path)
    return path


# --- initialize_database ---

def test_creates_database_file(tmp_path):
    path = str(tmp_path / "flights.db")
    initialize_database(path)
    assert (tmp_path / "flights.db").exists()


def test_creates_nested_directory(tmp_path):
    path = str(tmp_path / "data" / "subdir" / "flights.db")
    initialize_database(path)
    assert (tmp_path / "data" / "subdir" / "flights.db").exists()


def test_idempotent_when_called_twice(tmp_path):
    path = str(tmp_path / "flights.db")
    initialize_database(path)
    initialize_database(path)  # must not raise


def test_table_has_expected_columns(db_path):
    conn = sqlite3.connect(db_path)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(flight_observations)")}
    conn.close()
    expected = {
        "id", "retrieved_at", "departure_date", "origin", "destination",
        "airline", "departure_time", "arrival_time", "duration", "stops",
        "price", "price_amount", "price_currency", "is_best", "current_price_trend",
    }
    assert expected.issubset(cols)


def test_index_exists(db_path):
    conn = sqlite3.connect(db_path)
    indexes = {row[1] for row in conn.execute("PRAGMA index_list(flight_observations)")}
    conn.close()
    assert len(indexes) >= 1


# --- insert_observations ---

def test_insert_returns_count(db_path):
    count = insert_observations(db_path, [SAMPLE, SAMPLE])
    assert count == 2


def test_inserted_rows_are_readable(db_path):
    insert_observations(db_path, [SAMPLE])
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT * FROM flight_observations").fetchall()
    conn.close()
    assert len(rows) == 1


def test_insert_empty_list_returns_zero(db_path):
    assert insert_observations(db_path, []) == 0


def test_insert_rolls_back_on_failure(db_path):
    # A row with origin=None violates the NOT NULL constraint.
    invalid = {**SAMPLE, "origin": None}
    with pytest.raises(sqlite3.IntegrityError):
        insert_observations(db_path, [SAMPLE, invalid])
    # Neither row should be committed.
    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM flight_observations").fetchone()[0]
    conn.close()
    assert count == 0


# --- query_price_history ---

def test_query_returns_rows_for_date(db_path):
    insert_observations(db_path, [SAMPLE])
    rows = query_price_history(db_path, "2025-09-05")
    assert len(rows) == 1


def test_query_returns_empty_for_unknown_date(db_path):
    insert_observations(db_path, [SAMPLE])
    assert query_price_history(db_path, "2030-01-01") == []


def test_query_filters_by_origin(db_path):
    other = {**SAMPLE, "origin": "AMS", "destination": "CPH"}
    insert_observations(db_path, [SAMPLE, other])
    rows = query_price_history(db_path, "2025-09-05", origin="CPH")
    assert all(r["origin"] == "CPH" for r in rows)
    assert len(rows) == 1


def test_query_filters_by_destination(db_path):
    other = {**SAMPLE, "origin": "AMS", "destination": "CPH"}
    insert_observations(db_path, [SAMPLE, other])
    rows = query_price_history(db_path, "2025-09-05", destination="AMS")
    assert all(r["destination"] == "AMS" for r in rows)
    assert len(rows) == 1


def test_query_filters_by_airline(db_path):
    other = {**SAMPLE, "airline": "KLM"}
    insert_observations(db_path, [SAMPLE, other])
    rows = query_price_history(db_path, "2025-09-05", airline="KLM")
    assert len(rows) == 1
    assert rows[0]["airline"] == "KLM"


def test_query_returns_dicts(db_path):
    insert_observations(db_path, [SAMPLE])
    rows = query_price_history(db_path, "2025-09-05")
    assert isinstance(rows[0], dict)
    assert rows[0]["origin"] == "CPH"


def test_query_ordered_by_retrieved_at(db_path):
    early = {**SAMPLE, "retrieved_at": "2025-09-05T06:00:00"}
    late = {**SAMPLE, "retrieved_at": "2025-09-05T18:00:00"}
    insert_observations(db_path, [late, early])
    rows = query_price_history(db_path, "2025-09-05")
    assert rows[0]["retrieved_at"] == "2025-09-05T06:00:00"
    assert rows[1]["retrieved_at"] == "2025-09-05T18:00:00"
