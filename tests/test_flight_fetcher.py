import importlib
import logging
from datetime import date
from unittest.mock import MagicMock, patch

import fast_flights
import fast_flights.core
import pytest

import config
import src.flight_fetcher as flight_fetcher
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


def test_install_fetch_patch_refuses_invalid_impersonation(monkeypatch):
    """install_fetch_patch must REFUSE to start when config.IMPERSONATION
    names a profile that the installed primp version does not ship.

    primp's own behaviour on an unknown profile is to silently fall back to
    'random' (emits only a WARNING). That fallback gives every request a
    different TLS fingerprint and gets the scraper bot-walled within hours —
    the exact outcome that caused the captcha incident this guard is for.
    We promote primp's warning into a fatal RuntimeError so the failure mode
    can never silently degrade collection again.
    """
    import config as config_module
    import src.flight_fetcher as flight_fetcher_module

    monkeypatch.setattr(config_module, "IMPERSONATION", "chrome_does_not_exist")

    # Sentinel: confirm fast_flights.core.fetch is NOT rebound on failure.
    sentinel = object()
    monkeypatch.setattr(fast_flights.core, "fetch", sentinel)

    with pytest.raises(RuntimeError, match="chrome_does_not_exist"):
        flight_fetcher_module.install_fetch_patch()
    assert fast_flights.core.fetch is sentinel


# --- Exception hierarchy & classification (issue #111) ---
#
# These tests refer to exception classes via the `flight_fetcher` module
# attribute rather than top-level imports. The earlier #110 test
# (`test_module_import_does_not_install_patch`) reloads src.flight_fetcher,
# which mints fresh class objects — any class reference captured at test
# collection time becomes stale after that reload. Always re-deref through
# `flight_fetcher.X` so we see whichever version is currently bound.


def _good_body() -> str:
    """A response body long enough to clear BOT_CHALLENGE_MIN_BYTES and clean
    of any of the configured challenge-page substrings."""
    return "x" * (config.BOT_CHALLENGE_MIN_BYTES + 1000)


def _make_response(status_code: int, body: str = "") -> MagicMock:
    res = MagicMock()
    res.status_code = status_code
    res.text = body
    res.text_markdown = body
    return res


def test_exception_hierarchy_subclasses_flight_fetch_error():
    assert issubclass(flight_fetcher.BotChallengeError, flight_fetcher.FlightFetchError)
    assert issubclass(flight_fetcher.RateLimitedError, flight_fetcher.FlightFetchError)
    assert issubclass(flight_fetcher.NetworkError, flight_fetcher.FlightFetchError)
    assert issubclass(flight_fetcher.ParseError, flight_fetcher.FlightFetchError)


def test_patched_fetch_raises_rate_limited_on_429():
    with patch("src.flight_fetcher.Client") as mock_client:
        mock_client.return_value.get.return_value = _make_response(429)
        with pytest.raises(flight_fetcher.RateLimitedError, match="HTTP 429"):
            flight_fetcher.patched_fetch({})


def test_patched_fetch_raises_rate_limited_on_403():
    with patch("src.flight_fetcher.Client") as mock_client:
        mock_client.return_value.get.return_value = _make_response(403)
        with pytest.raises(flight_fetcher.RateLimitedError, match="HTTP 403"):
            flight_fetcher.patched_fetch({})


def test_patched_fetch_raises_bot_challenge_on_short_body():
    short = "tiny" * 10  # well below the 10 KB floor
    with patch("src.flight_fetcher.Client") as mock_client:
        mock_client.return_value.get.return_value = _make_response(200, short)
        with pytest.raises(
            flight_fetcher.BotChallengeError, match="below minimum length"
        ):
            flight_fetcher.patched_fetch({})


def test_patched_fetch_raises_bot_challenge_on_matching_pattern():
    # Body is long enough to clear the byte floor but contains a challenge
    # substring (mixed case to prove the match is case-insensitive).
    body = _good_body() + "Please verify you are not a CAPTCHA bot"
    with patch("src.flight_fetcher.Client") as mock_client:
        mock_client.return_value.get.return_value = _make_response(200, body)
        with pytest.raises(
            flight_fetcher.BotChallengeError, match="detected pattern: captcha"
        ):
            flight_fetcher.patched_fetch({})


def test_patched_fetch_raises_bot_challenge_on_consent_substring():
    body = _good_body() + "Before you continue, please accept cookie CONSENT"
    with patch("src.flight_fetcher.Client") as mock_client:
        mock_client.return_value.get.return_value = _make_response(200, body)
        with pytest.raises(
            flight_fetcher.BotChallengeError, match="detected pattern: consent"
        ):
            flight_fetcher.patched_fetch({})


def test_patched_fetch_raises_network_error_on_connection_error():
    with patch("src.flight_fetcher.Client") as mock_client:
        mock_client.return_value.get.side_effect = ConnectionError("dns failed")
        with pytest.raises(flight_fetcher.NetworkError, match="dns failed"):
            flight_fetcher.patched_fetch({})


def test_patched_fetch_raises_network_error_on_timeout():
    with patch("src.flight_fetcher.Client") as mock_client:
        mock_client.return_value.get.side_effect = TimeoutError("read timeout")
        with pytest.raises(flight_fetcher.NetworkError, match="read timeout"):
            flight_fetcher.patched_fetch({})


def test_patched_fetch_returns_response_on_clean_200():
    res = _make_response(200, _good_body())
    with patch("src.flight_fetcher.Client") as mock_client:
        mock_client.return_value.get.return_value = res
        assert flight_fetcher.patched_fetch({}) is res


def test_fetch_flights_for_date_propagates_classified_exceptions_when_raising():
    """When raise_on_failure=True, BotChallengeError / RateLimitedError must
    propagate so the orchestrator can classify them — NOT be swallowed into
    a generic None.
    """
    with patch(
        "fast_flights.get_flights",
        side_effect=flight_fetcher.BotChallengeError("blocked"),
    ):
        with pytest.raises(flight_fetcher.BotChallengeError):
            fetch_flights_for_date(
                ORIGIN, DESTINATION, DEPARTURE, raise_on_failure=True
            )

    with patch(
        "fast_flights.get_flights",
        side_effect=flight_fetcher.RateLimitedError("HTTP 429"),
    ):
        with pytest.raises(flight_fetcher.RateLimitedError):
            fetch_flights_for_date(
                ORIGIN, DESTINATION, DEPARTURE, raise_on_failure=True
            )


def test_fetch_flights_for_date_swallows_classified_exceptions_without_raise():
    """Default raise_on_failure=False keeps the original "log + return None"
    behaviour even for the new typed exceptions."""
    with patch(
        "fast_flights.get_flights",
        side_effect=flight_fetcher.BotChallengeError("blocked"),
    ):
        assert fetch_flights_for_date(ORIGIN, DESTINATION, DEPARTURE) is None


# --- Proxy injection tests ---


def test_set_current_proxy_sets_module_state():
    """set_current_proxy stores the proxy URL in module state."""
    from src import flight_fetcher as ff_module

    ff_module.set_current_proxy("http://user:pass@host:8080")
    assert ff_module._current_proxy == "http://user:pass@host:8080"

    ff_module.set_current_proxy(None)
    assert ff_module._current_proxy is None


def test_patched_fetch_passes_proxy_to_client():
    """patched_fetch should pass _current_proxy to primp.Client."""
    from src import flight_fetcher as ff_module

    ff_module._current_proxy = "http://test:test@proxy:1234"

    mock_client_instance = MagicMock()
    mock_client_instance.get.return_value = MagicMock(
        status_code=200,
        text="x" * 20000,
    )

    with patch("src.flight_fetcher.Client") as MockClient:
        MockClient.return_value = mock_client_instance
        try:
            ff_module.patched_fetch({"test": "params"})
        except Exception:
            pass  # We only care about the Client constructor call

        MockClient.assert_called_once_with(
            impersonate="chrome_131",
            verify=False,
            proxy="http://test:test@proxy:1234",
        )

    # Clean up
    ff_module._current_proxy = None
