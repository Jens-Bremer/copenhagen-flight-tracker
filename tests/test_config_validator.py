import pytest

from src.config_validator import validate_config


def _cfg(**overrides):
    """Return a valid base config dict, with optional overrides."""
    base = {
        "ROUTES": [("CPH", "AMS"), ("AMS", "CPH")],
        "DEPARTURE_WEEKDAYS": [4, 5, 6],
        "MAX_MONTHS_AHEAD": 6,
        "DAILY_WINDOW_START_HOUR": 6,
        "DAILY_WINDOW_END_HOUR": 22,
        "DATABASE_PATH": "data/flights.db",
    }
    base.update(overrides)
    return base


def test_valid_config_passes():
    validate_config(_cfg())  # must not raise


# --- ROUTES ---

def test_empty_routes_raises():
    with pytest.raises(ValueError, match="ROUTES"):
        validate_config(_cfg(ROUTES=[]))


def test_routes_not_a_list_raises():
    with pytest.raises(ValueError, match="ROUTES"):
        validate_config(_cfg(ROUTES="CPH-AMS"))


def test_route_wrong_length_raises():
    with pytest.raises(ValueError, match="ROUTES"):
        validate_config(_cfg(ROUTES=[("CPH",)]))


def test_route_non_string_airport_raises():
    with pytest.raises(ValueError, match="ROUTES"):
        validate_config(_cfg(ROUTES=[(1, "AMS")]))


def test_duplicate_routes_raises():
    with pytest.raises(ValueError, match="ROUTES"):
        validate_config(_cfg(ROUTES=[("CPH", "AMS"), ("CPH", "AMS")]))


# --- DEPARTURE_WEEKDAYS ---

def test_empty_departure_weekdays_raises():
    with pytest.raises(ValueError, match="DEPARTURE_WEEKDAYS"):
        validate_config(_cfg(DEPARTURE_WEEKDAYS=[]))


def test_weekday_out_of_range_raises():
    with pytest.raises(ValueError, match="DEPARTURE_WEEKDAYS"):
        validate_config(_cfg(DEPARTURE_WEEKDAYS=[4, 5, 7]))


def test_negative_weekday_raises():
    with pytest.raises(ValueError, match="DEPARTURE_WEEKDAYS"):
        validate_config(_cfg(DEPARTURE_WEEKDAYS=[-1, 5]))


# --- MAX_MONTHS_AHEAD ---

def test_max_months_zero_raises():
    with pytest.raises(ValueError, match="MAX_MONTHS_AHEAD"):
        validate_config(_cfg(MAX_MONTHS_AHEAD=0))


def test_max_months_negative_raises():
    with pytest.raises(ValueError, match="MAX_MONTHS_AHEAD"):
        validate_config(_cfg(MAX_MONTHS_AHEAD=-3))


def test_max_months_non_int_raises():
    with pytest.raises(ValueError, match="MAX_MONTHS_AHEAD"):
        validate_config(_cfg(MAX_MONTHS_AHEAD=1.5))


# --- Window hours ---

def test_start_hour_equal_to_end_hour_raises():
    with pytest.raises(ValueError, match="DAILY_WINDOW"):
        validate_config(_cfg(DAILY_WINDOW_START_HOUR=6, DAILY_WINDOW_END_HOUR=6))


def test_start_hour_after_end_hour_raises():
    with pytest.raises(ValueError, match="DAILY_WINDOW"):
        validate_config(_cfg(DAILY_WINDOW_START_HOUR=22, DAILY_WINDOW_END_HOUR=6))


def test_window_hour_out_of_range_raises():
    with pytest.raises(ValueError, match="DAILY_WINDOW"):
        validate_config(_cfg(DAILY_WINDOW_START_HOUR=-1))


# --- DATABASE_PATH ---

def test_empty_database_path_raises():
    with pytest.raises(ValueError, match="DATABASE_PATH"):
        validate_config(_cfg(DATABASE_PATH=""))


def test_none_database_path_raises():
    with pytest.raises(ValueError, match="DATABASE_PATH"):
        validate_config(_cfg(DATABASE_PATH=None))
