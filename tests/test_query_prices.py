from scripts import query_prices
from src.database import initialize_database, insert_observations


def _obs(price_amount: int, retrieved_at: str) -> dict:
    return {
        "retrieved_at": retrieved_at,
        "departure_date": "2099-01-01",
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
        "duration_minutes": 90,
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


def test_cmd_health_healthy_state(tmp_path, monkeypatch, capsys):
    """Test --health when system is healthy (no issues)."""
    import json
    from datetime import date

    db_path = str(tmp_path / "flights.db")
    initialize_database(db_path)
    heartbeat_path = str(tmp_path / "last_run.json")

    # Write a valid heartbeat for today
    with open(heartbeat_path, "w") as f:
        json.dump(
            {
                "run_date": date.today().isoformat(),
                "total_observations": 42,
                "failed_jobs_count": 0,
                "total_jobs": 10,
                "duration_seconds": 120.5,
            },
            f,
        )

    # Add some observations for today
    today_iso = date.today().isoformat()
    insert_observations(
        db_path,
        [
            _obs(1000, f"{today_iso}T06:00:00+00:00"),
            _obs(2000, f"{today_iso}T07:00:00+00:00"),
        ],
    )

    monkeypatch.setattr(query_prices.config, "DATABASE_PATH", db_path)
    monkeypatch.setattr(
        query_prices, "run_health_check", lambda db, hb: []
    )  # No issues

    try:
        query_prices.cmd_health()
    except SystemExit as e:
        exit_code = e.code
    else:
        exit_code = None

    output = capsys.readouterr().out
    assert "Heartbeat:" in output
    assert "ok" in output
    assert "Total jobs:" in output
    assert "(none)" in output
    assert exit_code == 0


def test_cmd_health_with_failures(tmp_path, monkeypatch, capsys):
    """Test --health when there are failed jobs."""
    import json
    from datetime import date

    db_path = str(tmp_path / "flights.db")
    initialize_database(db_path)
    heartbeat_path = str(tmp_path / "last_run.json")

    # Write a heartbeat with failures
    with open(heartbeat_path, "w") as f:
        json.dump(
            {
                "run_date": date.today().isoformat(),
                "total_observations": 40,
                "failed_jobs_count": 1,
                "total_jobs": 10,
                "duration_seconds": 120.5,
            },
            f,
        )

    # Add some observations
    today_iso = date.today().isoformat()
    insert_observations(
        db_path,
        [
            _obs(1000, f"{today_iso}T06:00:00+00:00"),
            _obs(2000, f"{today_iso}T07:00:00+00:00"),
        ],
    )

    monkeypatch.setattr(query_prices.config, "DATABASE_PATH", db_path)
    # Mock health check to return an issue
    monkeypatch.setattr(
        query_prices,
        "run_health_check",
        lambda db, hb: ["[high] Some issue detected"],
    )

    try:
        query_prices.cmd_health()
    except SystemExit as e:
        exit_code = e.code
    else:
        exit_code = None

    output = capsys.readouterr().out
    assert "Failed:           1" in output
    assert "10%" in output  # 1/10
    assert "[high] Some issue detected" in output
    assert exit_code == 1


def test_cmd_health_missing_heartbeat(tmp_path, monkeypatch, capsys):
    """Test --health when heartbeat is missing."""
    db_path = str(tmp_path / "flights.db")
    initialize_database(db_path)

    monkeypatch.setattr(query_prices.config, "DATABASE_PATH", db_path)
    monkeypatch.setattr(
        query_prices, "run_health_check", lambda db, hb: []
    )  # No issues

    try:
        query_prices.cmd_health()
    except SystemExit as e:
        exit_code = e.code
    else:
        exit_code = None

    output = capsys.readouterr().out
    assert "Heartbeat:" in output
    assert "missing (daemon may not have run yet)" in output
    assert "Total jobs:       0" in output
    assert "(none)" in output
    assert exit_code == 0
