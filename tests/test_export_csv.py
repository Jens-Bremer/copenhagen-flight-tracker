import csv
import os

import pytest

from scripts.export_csv import export_to_csv
from src.database import initialize_database, insert_observations

COLUMNS = [
    "retrieved_at",
    "departure_date",
    "origin",
    "destination",
    "airline",
    "departure_time",
    "arrival_time",
    "price_amount",
    "price_currency",
]


def _obs(
    price_amount=4500,
    origin="CPH",
    destination="AMS",
    departure_date="2025-09-19",
    departure_time="08:00",
    arrival_time="10:05",
    airline="SAS",
):
    return {
        "retrieved_at": "2025-09-14T06:00:00+00:00",
        "departure_date": departure_date,
        "origin": origin,
        "destination": destination,
        "airline": airline,
        "departure_time": departure_time,
        "arrival_time": arrival_time,
        "duration": "2h 5m",
        "stops": 0,
        "price": f"€{price_amount // 100}",
        "price_amount": price_amount,
        "price_currency": "EUR",
        "is_best": True,
        "current_price_trend": "low",
    }


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "flights.db")
    initialize_database(path)
    return path


@pytest.fixture
def output_path(tmp_path):
    return str(tmp_path / "flights_export.csv")


def test_creates_csv_file(db_path, output_path):
    insert_observations(db_path, [_obs()])
    export_to_csv(db_path, output_path)
    assert os.path.exists(output_path)


def test_csv_has_header_row(db_path, output_path):
    insert_observations(db_path, [_obs()])
    export_to_csv(db_path, output_path)
    with open(output_path) as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames is not None
        for col in COLUMNS:
            assert col in reader.fieldnames


def test_csv_contains_observation_data(db_path, output_path):
    insert_observations(
        db_path, [_obs(origin="CPH", destination="AMS", price_amount=4500)]
    )
    export_to_csv(db_path, output_path)
    with open(output_path) as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["origin"] == "CPH"
    assert rows[0]["destination"] == "AMS"
    assert rows[0]["price_amount"] == "4500"


def test_csv_contains_multiple_rows(db_path, output_path):
    insert_observations(
        db_path,
        [
            _obs(origin="CPH", destination="AMS"),
            _obs(origin="AMS", destination="CPH"),
        ],
    )
    export_to_csv(db_path, output_path)
    with open(output_path) as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2


def test_csv_overwrites_existing_file(db_path, output_path):
    insert_observations(db_path, [_obs(origin="CPH", destination="AMS")])
    export_to_csv(db_path, output_path)

    # now write only one different row to the db and re-export
    db2_path = db_path.replace("flights.db", "flights2.db")
    initialize_database(db2_path)
    insert_observations(db2_path, [_obs(origin="AMS", destination="CPH")])
    export_to_csv(db2_path, output_path)

    with open(output_path) as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["origin"] == "AMS"


def test_csv_empty_when_no_data(db_path, output_path):
    export_to_csv(db_path, output_path)
    with open(output_path) as f:
        rows = list(csv.DictReader(f))
    assert rows == []


def test_csv_creates_parent_directory(tmp_path, db_path):
    nested_output = str(tmp_path / "subdir" / "export.csv")
    insert_observations(db_path, [_obs()])
    export_to_csv(db_path, nested_output)
    assert os.path.exists(nested_output)
