from datetime import date
from unittest.mock import patch

import fast_flights
import pytest

import src.flight_fetcher as flight_fetcher
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


def test_returns_none_on_parse_error():
    with patch(
        "fast_flights.get_flights", side_effect=flight_fetcher.ParseError("bad JSON")
    ):
        result = fetch_flights_for_date(ORIGIN, DESTINATION, DEPARTURE)
    assert result is None


def test_propagates_bot_challenge_when_raise_on_failure():
    with patch(
        "fast_flights.get_flights",
        side_effect=flight_fetcher.BotChallengeError("captcha detected"),
    ):
        with pytest.raises(flight_fetcher.BotChallengeError):
            fetch_flights_for_date(
                ORIGIN, DESTINATION, DEPARTURE, raise_on_failure=True
            )


def test_propagates_rate_limited_when_raise_on_failure():
    with patch(
        "fast_flights.get_flights",
        side_effect=flight_fetcher.RateLimitedError("HTTP 429"),
    ):
        with pytest.raises(flight_fetcher.RateLimitedError):
            fetch_flights_for_date(
                ORIGIN, DESTINATION, DEPARTURE, raise_on_failure=True
            )


def test_propagates_network_error_when_raise_on_failure():
    with patch(
        "fast_flights.get_flights",
        side_effect=flight_fetcher.NetworkError("connection timeout"),
    ):
        with pytest.raises(flight_fetcher.NetworkError):
            fetch_flights_for_date(
                ORIGIN, DESTINATION, DEPARTURE, raise_on_failure=True
            )


def test_propagates_parse_error_when_raise_on_failure():
    with patch(
        "fast_flights.get_flights",
        side_effect=flight_fetcher.ParseError("bad JSON"),
    ):
        with pytest.raises(flight_fetcher.ParseError):
            fetch_flights_for_date(
                ORIGIN, DESTINATION, DEPARTURE, raise_on_failure=True
            )


def test_exception_hierarchy_subclasses_flight_fetch_error():
    assert issubclass(flight_fetcher.BotChallengeError, flight_fetcher.FlightFetchError)
    assert issubclass(flight_fetcher.RateLimitedError, flight_fetcher.FlightFetchError)
    assert issubclass(flight_fetcher.NetworkError, flight_fetcher.FlightFetchError)
    assert issubclass(flight_fetcher.ParseError, flight_fetcher.FlightFetchError)
