import importlib
import logging
from datetime import date
from unittest.mock import MagicMock, patch

import fast_flights
import fast_flights.core

from src.flight_fetcher import fetch_flights_for_date, install_fetch_patch

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


def test_returns_none_when_patched_fetch_gets_non_200(caplog, monkeypatch):
    bad_res = MagicMock()
    bad_res.status_code = 429
    bad_res.text_markdown = "rate limited"

    # This test exercises the patched_fetch code path (mocking the primp
    # Client inside it). For fast_flights.get_flights to route into
    # patched_fetch we must install the patch explicitly — the module no
    # longer does it at import time. monkeypatch.setattr restores the
    # original fetch when the test ends, so other tests stay isolated.
    monkeypatch.setattr(fast_flights.core, "fetch", fast_flights.core.fetch)
    install_fetch_patch()

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


def test_module_import_does_not_install_patch(monkeypatch):
    """Importing src.flight_fetcher must NOT rebind fast_flights.core.fetch.

    The patch is a process-wide side effect; it must only happen when callers
    explicitly opt in via install_fetch_patch(). Anything else — tests, the
    REPL, future analytics modules that transitively import flight_fetcher —
    must see the pristine upstream fetch.
    """
    # Install a sentinel as the "original" fetch so we can detect rebinding
    # even on a fresh process where the patch has never been applied.
    sentinel = object()
    monkeypatch.setattr(fast_flights.core, "fetch", sentinel)

    # Reload src.flight_fetcher so its module-level code re-executes under
    # the sentinel. If the old side effect were still present, this would
    # rebind fast_flights.core.fetch to patched_fetch.
    import src.flight_fetcher as flight_fetcher_module

    importlib.reload(flight_fetcher_module)
    assert fast_flights.core.fetch is sentinel

    # Explicit call MUST rebind it.
    flight_fetcher_module.install_fetch_patch()
    assert fast_flights.core.fetch is flight_fetcher_module.patched_fetch
