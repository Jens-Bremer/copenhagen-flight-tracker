import logging
from datetime import date
from unittest.mock import MagicMock, patch

import fast_flights

from src.flight_fetcher import fetch_flights_for_date


ORIGIN = "CPH"
DESTINATION = "AMS"
DEPARTURE = date(2025, 9, 5)


def _make_result():
    return fast_flights.Result(current_price="typical", flights=[])


def test_returns_result_on_success():
    expected = _make_result()
    with patch("fast_flights.get_flights", return_value=expected):
        result = fetch_flights_for_date(ORIGIN, DESTINATION, DEPARTURE)
    assert result is expected


def test_returns_none_on_exception():
    with patch("fast_flights.get_flights", side_effect=Exception("network error")):
        result = fetch_flights_for_date(ORIGIN, DESTINATION, DEPARTURE)
    assert result is None


def test_returns_none_when_patched_fetch_gets_non_200(caplog):
    bad_res = MagicMock()
    bad_res.status_code = 429
    bad_res.text_markdown = "rate limited"

    with patch("src.flight_fetcher.Client") as mock_client:
        mock_client.return_value.get.return_value = bad_res
        with caplog.at_level(logging.ERROR, logger="src.flight_fetcher"):
            assert fetch_flights_for_date(ORIGIN, DESTINATION, DEPARTURE) is None

    assert "HTTP 429" in caplog.text


def test_passes_correct_trip_and_seat():
    with patch("fast_flights.get_flights", return_value=_make_result()) as mock_get:
        fetch_flights_for_date(ORIGIN, DESTINATION, DEPARTURE)
    _, kwargs = mock_get.call_args
    assert kwargs["trip"] == "one-way"
    assert kwargs["seat"] == "economy"


def test_passes_fallback_fetch_mode():
    with patch("fast_flights.get_flights", return_value=_make_result()) as mock_get:
        fetch_flights_for_date(ORIGIN, DESTINATION, DEPARTURE)
    _, kwargs = mock_get.call_args
    assert kwargs["fetch_mode"] == "common"


def test_passes_nonstop_filter():
    with patch("fast_flights.get_flights", return_value=_make_result()) as mock_get:
        fetch_flights_for_date(ORIGIN, DESTINATION, DEPARTURE)
    _, kwargs = mock_get.call_args
    assert kwargs["max_stops"] == 0


def test_passes_correct_airports_and_date():
    with patch("fast_flights.get_flights", return_value=_make_result()) as mock_get:
        fetch_flights_for_date(ORIGIN, DESTINATION, DEPARTURE)
    _, kwargs = mock_get.call_args
    flight_data = kwargs["flight_data"][0]
    assert flight_data.from_airport == ORIGIN
    assert flight_data.to_airport == DESTINATION
    assert flight_data.date == DEPARTURE.strftime("%Y-%m-%d")


def test_passes_correct_passenger_count():
    with patch("fast_flights.get_flights", return_value=_make_result()) as mock_get:
        fetch_flights_for_date(ORIGIN, DESTINATION, DEPARTURE)
    _, kwargs = mock_get.call_args
    assert (
        kwargs["passengers"]._data[0] == 1
    )  # _data is (adults, children, infants_in_seat, infants_on_lap)


def test_logs_route_and_date_on_success(caplog):
    with patch("fast_flights.get_flights", return_value=_make_result()):
        with caplog.at_level(logging.INFO, logger="src.flight_fetcher"):
            fetch_flights_for_date(ORIGIN, DESTINATION, DEPARTURE)
    assert "CPH" in caplog.text
    assert "AMS" in caplog.text
    assert "2025-09-05" in caplog.text


def test_logs_error_on_failure(caplog):
    with patch("fast_flights.get_flights", side_effect=Exception("timeout")):
        with caplog.at_level(logging.ERROR, logger="src.flight_fetcher"):
            fetch_flights_for_date(ORIGIN, DESTINATION, DEPARTURE)
    assert "timeout" in caplog.text
