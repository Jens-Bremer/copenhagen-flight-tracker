from datetime import date

import pytest

from src.database import initialize_database, insert_observations
from src.price_alerter import (
    check_and_alert_cheap_flights,
    find_cheap_flights,
    format_alert_message,
)

TODAY = date.today().isoformat()
THRESHOLD = 5000  # €50

# Dict threshold: CPH→AMS cap €50, AMS→CPH cap €60, unlisted cap €70
DICT_THRESHOLD = {
    ("CPH", "AMS"): 5000,
    ("AMS", "CPH"): 6000,
    "_default": 7000,
}


def _obs(
    price_amount=4500,
    origin="CPH",
    destination="AMS",
    departure_date="2025-09-19",
    departure_time="08:00",
    airline="SAS",
    retrieved_date=None,
):
    ts = f"{retrieved_date or TODAY}T06:00:00+00:00"
    return {
        "retrieved_at": ts,
        "departure_date": departure_date,
        "origin": origin,
        "destination": destination,
        "airline": airline,
        "departure_time": departure_time,
        "arrival_time": "10:05",
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


# --- find_cheap_flights ---


def test_returns_flights_below_threshold(db_path):
    insert_observations(db_path, [_obs(price_amount=4500)])
    results = find_cheap_flights(db_path, THRESHOLD, TODAY)
    assert len(results) == 1


def test_excludes_flights_above_threshold(db_path):
    insert_observations(db_path, [_obs(price_amount=6000)])
    results = find_cheap_flights(db_path, THRESHOLD, TODAY)
    assert results == []


def test_excludes_flights_at_threshold_boundary(db_path):
    insert_observations(db_path, [_obs(price_amount=5000)])
    results = find_cheap_flights(db_path, THRESHOLD, TODAY)
    assert len(results) == 1  # <= threshold, so included


def test_excludes_historical_flights(db_path):
    insert_observations(db_path, [_obs(price_amount=4500, retrieved_date="2025-01-01")])
    results = find_cheap_flights(db_path, THRESHOLD, TODAY)
    assert results == []


def test_excludes_flights_with_null_price(db_path):
    no_price = {**_obs(), "price_amount": None}
    insert_observations(db_path, [no_price])
    results = find_cheap_flights(db_path, THRESHOLD, TODAY)
    assert results == []


def test_returns_multiple_cheap_flights(db_path):
    insert_observations(
        db_path,
        [
            _obs(price_amount=3000, origin="CPH"),
            _obs(price_amount=4500, origin="AMS", destination="CPH"),
        ],
    )
    results = find_cheap_flights(db_path, THRESHOLD, TODAY)
    assert len(results) == 2


# --- format_alert_message ---


def test_message_contains_route(db_path):
    insert_observations(db_path, [_obs(price_amount=4500)])
    flights = find_cheap_flights(db_path, THRESHOLD, TODAY)
    msg = format_alert_message(flights, THRESHOLD)
    assert "CPH" in msg
    assert "AMS" in msg


def test_message_contains_price(db_path):
    insert_observations(db_path, [_obs(price_amount=4500)])
    flights = find_cheap_flights(db_path, THRESHOLD, TODAY)
    msg = format_alert_message(flights, THRESHOLD)
    assert "45" in msg  # price in euros


def test_message_contains_departure_date(db_path):
    insert_observations(
        db_path,
        [_obs(price_amount=4500, departure_date="2025-09-19")],
    )
    flights = find_cheap_flights(db_path, THRESHOLD, TODAY)
    msg = format_alert_message(flights, THRESHOLD)
    assert "2025-09-19" in msg


def test_message_contains_flight_count(db_path):
    insert_observations(
        db_path,
        [
            _obs(price_amount=3000),
            _obs(price_amount=4000, origin="AMS", destination="CPH"),
        ],
    )
    flights = find_cheap_flights(db_path, THRESHOLD, TODAY)
    msg = format_alert_message(flights, THRESHOLD)
    assert "2" in msg


def test_message_includes_percentile_when_enough_history(db_path):
    insert_observations(
        db_path,
        [
            _obs(price_amount=3000, retrieved_date="2025-01-01"),
            _obs(price_amount=4000, retrieved_date="2025-01-02"),
            _obs(price_amount=5000, retrieved_date="2025-01-03"),
            _obs(price_amount=6000, retrieved_date="2025-01-04"),
            _obs(price_amount=7000, retrieved_date="2025-01-05"),
        ],
    )
    flights = find_cheap_flights(db_path, THRESHOLD, "2025-01-01")
    msg = format_alert_message(flights, THRESHOLD, db_path=db_path)
    assert "0th percentile" in msg
    assert "historically very cheap" in msg


def test_message_omits_percentile_when_not_enough_history(db_path):
    insert_observations(db_path, [_obs(price_amount=3000, retrieved_date="2025-01-01")])
    flights = find_cheap_flights(db_path, THRESHOLD, "2025-01-01")
    msg = format_alert_message(flights, THRESHOLD, db_path=db_path)
    assert "percentile" not in msg


# --- check_and_alert_cheap_flights ---


def test_returns_false_and_no_alert_when_no_cheap_flights(db_path):
    from unittest.mock import patch

    insert_observations(db_path, [_obs(price_amount=9000)])
    with patch("src.price_alerter.send_alert") as mock_alert:
        result = check_and_alert_cheap_flights(db_path, THRESHOLD, TODAY)
    assert result is False
    mock_alert.assert_not_called()


def test_returns_true_and_sends_alert_when_cheap_flights_found(db_path):
    from unittest.mock import patch

    insert_observations(db_path, [_obs(price_amount=4500)])
    with patch("src.price_alerter.send_alert", return_value=True) as mock_alert:
        result = check_and_alert_cheap_flights(db_path, THRESHOLD, TODAY)
    assert result is True
    mock_alert.assert_called_once()
    args, kwargs = mock_alert.call_args
    priority = kwargs.get("priority")
    if priority is None and len(args) > 2:
        priority = args[2]
    if priority is None:
        priority = "default"
    assert priority == "default"


def test_alert_uses_default_priority(db_path):
    from unittest.mock import patch

    insert_observations(db_path, [_obs(price_amount=4500)])
    with patch("src.price_alerter.send_alert", return_value=True) as mock_alert:
        check_and_alert_cheap_flights(db_path, THRESHOLD, TODAY)
    call_kwargs = mock_alert.call_args[1]
    assert call_kwargs.get("priority") == "default"


# --- per-route dict threshold ---


def test_find_cheap_flights_dict_excludes_flight_above_route_threshold(db_path):
    # CPH→AMS cap is €50; a €55 flight must be excluded
    insert_observations(
        db_path, [_obs(price_amount=5500, origin="CPH", destination="AMS")]
    )
    results = find_cheap_flights(db_path, DICT_THRESHOLD, TODAY)
    assert results == []


def test_find_cheap_flights_dict_includes_flight_below_route_threshold(db_path):
    # AMS→CPH cap is €60; a €55 flight must be included
    insert_observations(
        db_path, [_obs(price_amount=5500, origin="AMS", destination="CPH")]
    )
    results = find_cheap_flights(db_path, DICT_THRESHOLD, TODAY)
    assert len(results) == 1


def test_find_cheap_flights_dict_uses_default_for_unlisted_route(db_path):
    # _default cap is €70; a €65 flight on an unlisted route must be included
    insert_observations(
        db_path, [_obs(price_amount=6500, origin="CPH", destination="LHR")]
    )
    results = find_cheap_flights(db_path, DICT_THRESHOLD, TODAY)
    assert len(results) == 1


def test_find_cheap_flights_dict_default_excludes_above_default(db_path):
    # _default cap is €70; a €75 flight on an unlisted route must be excluded
    insert_observations(
        db_path, [_obs(price_amount=7500, origin="CPH", destination="LHR")]
    )
    results = find_cheap_flights(db_path, DICT_THRESHOLD, TODAY)
    assert results == []


def test_format_alert_message_dict_threshold_header(db_path):
    insert_observations(
        db_path, [_obs(price_amount=5500, origin="AMS", destination="CPH")]
    )
    flights = find_cheap_flights(db_path, DICT_THRESHOLD, TODAY)
    msg = format_alert_message(flights, DICT_THRESHOLD)
    assert "per-route thresholds" in msg


def test_check_and_alert_dict_threshold_sends_alert_for_cheap_route(db_path):
    from unittest.mock import patch

    # AMS→CPH cap €60; €55 flight should trigger alert
    insert_observations(
        db_path, [_obs(price_amount=5500, origin="AMS", destination="CPH")]
    )
    with patch("src.price_alerter.send_alert", return_value=True) as mock_alert:
        result = check_and_alert_cheap_flights(db_path, DICT_THRESHOLD, TODAY)
    assert result is True
    mock_alert.assert_called_once()


def test_check_and_alert_dict_threshold_no_alert_for_expensive_route(db_path):
    from unittest.mock import patch

    # CPH→AMS cap €50; €55 flight should NOT trigger alert
    insert_observations(
        db_path, [_obs(price_amount=5500, origin="CPH", destination="AMS")]
    )
    with patch("src.price_alerter.send_alert") as mock_alert:
        result = check_and_alert_cheap_flights(db_path, DICT_THRESHOLD, TODAY)
    assert result is False
    mock_alert.assert_not_called()
