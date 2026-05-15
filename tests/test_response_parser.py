from datetime import date, datetime, timezone

import fast_flights

from src.response_parser import extract_price_parts, parse_flights


def _make_flight(price="€89", stops=0, is_best=True):
    return fast_flights.Flight(
        is_best=is_best,
        name="SAS",
        departure="08:00",
        arrival="10:05",
        arrival_time_ahead="",
        duration="2h 5m",
        stops=stops,
        delay=None,
        price=price,
    )


def _make_result(flights=None, current_price="typical"):
    return fast_flights.Result(
        current_price=current_price,
        flights=flights if flights is not None else [_make_flight()],
    )


ORIGIN = "CPH"
DEST = "AMS"
DEP_DATE = date(2025, 9, 5)
RETRIEVED = datetime(2025, 9, 5, 6, 0, 0, tzinfo=timezone.utc)


# --- parse_flights ---


def test_none_result_returns_empty_list():
    assert parse_flights(None, ORIGIN, DEST, DEP_DATE, RETRIEVED) == []


def test_returns_one_row_per_flight():
    result = _make_result(flights=[_make_flight(), _make_flight()])
    rows = parse_flights(result, ORIGIN, DEST, DEP_DATE, RETRIEVED)
    assert len(rows) == 2


def test_row_contains_all_required_keys():
    rows = parse_flights(_make_result(), ORIGIN, DEST, DEP_DATE, RETRIEVED)
    expected_keys = {
        "retrieved_at",
        "departure_date",
        "origin",
        "destination",
        "airline",
        "departure_time",
        "arrival_time",
        "duration",
        "stops",
        "price",
        "price_amount",
        "price_currency",
        "is_best",
        "current_price_trend",
    }
    assert set(rows[0].keys()) == expected_keys


def test_row_values_mapped_correctly():
    rows = parse_flights(_make_result(), ORIGIN, DEST, DEP_DATE, RETRIEVED)
    row = rows[0]
    assert row["origin"] == "CPH"
    assert row["destination"] == "AMS"
    assert row["departure_date"] == "2025-09-05"
    assert row["airline"] == "SAS"
    assert row["departure_time"] == "08:00"
    assert row["arrival_time"] == "10:05"
    assert row["duration"] == "2h 5m"
    assert row["stops"] == 0
    assert row["price"] == "€89"
    assert row["price_amount"] == 8900
    assert row["price_currency"] == "EUR"
    assert row["is_best"] is True
    assert row["current_price_trend"] == "typical"


def test_retrieved_at_is_iso8601():
    rows = parse_flights(_make_result(), ORIGIN, DEST, DEP_DATE, RETRIEVED)
    assert rows[0]["retrieved_at"] == RETRIEVED.isoformat()


def test_missing_price_yields_none_amount_and_currency():
    result = _make_result(flights=[_make_flight(price="")])
    rows = parse_flights(result, ORIGIN, DEST, DEP_DATE, RETRIEVED)
    assert rows[0]["price_amount"] is None
    assert rows[0]["price_currency"] is None


# --- extract_price_parts ---


def test_euro_price():
    assert extract_price_parts("€89") == (8900, "EUR")


def test_euro_price_with_decimal():
    assert extract_price_parts("€89.50") == (8950, "EUR")


def test_dollar_price():
    assert extract_price_parts("$120") == (12000, "USD")


def test_pound_price():
    assert extract_price_parts("£75") == (7500, "GBP")


def test_unknown_symbol_returns_none():
    assert extract_price_parts("¥5000") == (None, None)


def test_unknown_symbol_logs_warning(caplog):
    with caplog.at_level("WARNING", logger="src.response_parser"):
        assert extract_price_parts("¥5000") == (None, None)
    assert "Unknown currency symbol" in caplog.text


def test_none_input_returns_none():
    assert extract_price_parts(None) == (None, None)


def test_empty_string_returns_none():
    assert extract_price_parts("") == (None, None)


def test_kr_prefix_parses_as_sek():
    assert extract_price_parts("kr123") == (12300, "SEK")


def test_fr_prefix_parses_as_chf():
    assert extract_price_parts("Fr89") == (8900, "CHF")


def test_zloty_symbol_parses_as_pln():
    assert extract_price_parts("zł75") == (7500, "PLN")
