from scripts import query_prices
from src.database import initialize_database, insert_observations


def _obs(price_amount: int, retrieved_at: str) -> dict:
    return {
        "retrieved_at": retrieved_at,
        "departure_date": "2026-06-01",
        "origin": "CPH",
        "destination": "AMS",
        "airline": "SAS",
        "departure_time": "08:00",
        "arrival_time": "09:30",
        "duration": "1h 30m",
        "stops": 0,
        "price": f"€{price_amount // 100}",
        "price_amount": price_amount,
        "price_currency": "EUR",
        "is_best": True,
        "current_price_trend": "low",
    }


def test_cmd_cheapest_shows_percentile_when_enough_data(tmp_path, monkeypatch, capsys):
    db_path = str(tmp_path / "flights.db")
    initialize_database(db_path)
    insert_observations(
        db_path,
        [
            _obs(1000, "2026-01-01T06:00:00+00:00"),
            _obs(2000, "2026-01-02T06:00:00+00:00"),
            _obs(3000, "2026-01-03T06:00:00+00:00"),
            _obs(4000, "2026-01-04T06:00:00+00:00"),
            _obs(5000, "2026-01-05T06:00:00+00:00"),
        ],
    )
    monkeypatch.setattr(query_prices.config, "DATABASE_PATH", db_path)
    query_prices.cmd_cheapest()
    output = capsys.readouterr().out

    assert "0th percentile" in output


def test_cmd_cheapest_omits_percentile_when_not_enough_data(
    tmp_path, monkeypatch, capsys
):
    db_path = str(tmp_path / "flights.db")
    initialize_database(db_path)
    insert_observations(
        db_path,
        [
            _obs(1000, "2026-01-01T06:00:00+00:00"),
            _obs(2000, "2026-01-02T06:00:00+00:00"),
            _obs(3000, "2026-01-03T06:00:00+00:00"),
            _obs(4000, "2026-01-04T06:00:00+00:00"),
        ],
    )
    monkeypatch.setattr(query_prices.config, "DATABASE_PATH", db_path)
    query_prices.cmd_cheapest()
    output = capsys.readouterr().out

    assert "percentile" not in output
