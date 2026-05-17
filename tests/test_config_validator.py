import pytest

from src.config_validator import validate_config


def _cfg(**overrides):
    """Return a valid base config dict, with optional overrides."""
    base = {
        "ROUTES": [("CPH", "AMS"), ("AMS", "CPH")],
        "DEPARTURE_WEEKDAYS": [4, 5, 6],
        "MAX_MONTHS_AHEAD": 6,
        "MAX_STOPS": 0,
        "DAILY_WINDOW_START_HOUR": 6,
        "DAILY_WINDOW_END_HOUR": 22,
        "MIN_REQUEST_INTERVAL_SECONDS": 120,
        "FETCH_RETRY_DELAY_SECONDS": 60,
        "DATABASE_PATH": "data/flights.db",
        "BACKUP_DIR": "data/backups",
        "BACKUP_KEEP_LAST_N": 7,
        "HEALTH_FAILURE_RATE_THRESHOLD": 0.25,
        "HEALTH_COUNT_DROP_THRESHOLD": 0.5,
        "PRICE_ALERT_THRESHOLD": 5000,
        "LOG_DIR": "logs",
        "LOG_KEEP_DAYS": 14,
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


# --- MAX_STOPS ---


def test_max_stops_none_raises():
    with pytest.raises(ValueError, match="MAX_STOPS"):
        validate_config(_cfg(MAX_STOPS=None))


def test_max_stops_negative_raises():
    with pytest.raises(ValueError, match="MAX_STOPS"):
        validate_config(_cfg(MAX_STOPS=-1))


def test_max_stops_bool_raises():
    with pytest.raises(ValueError, match="MAX_STOPS"):
        validate_config(_cfg(MAX_STOPS=True))


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


# --- MIN_REQUEST_INTERVAL_SECONDS ---


def test_min_request_interval_zero_raises():
    with pytest.raises(ValueError, match="MIN_REQUEST_INTERVAL_SECONDS"):
        validate_config(_cfg(MIN_REQUEST_INTERVAL_SECONDS=0))


def test_min_request_interval_negative_raises():
    with pytest.raises(ValueError, match="MIN_REQUEST_INTERVAL_SECONDS"):
        validate_config(_cfg(MIN_REQUEST_INTERVAL_SECONDS=-1))


# --- FETCH_RETRY_DELAY_SECONDS ---


def test_fetch_retry_delay_zero_is_valid():
    validate_config(_cfg(FETCH_RETRY_DELAY_SECONDS=0))  # 0 disables inter-retry sleep


def test_fetch_retry_delay_float_is_valid():
    validate_config(_cfg(FETCH_RETRY_DELAY_SECONDS=300.5))


def test_fetch_retry_delay_none_raises():
    with pytest.raises(ValueError, match="FETCH_RETRY_DELAY_SECONDS"):
        validate_config(_cfg(FETCH_RETRY_DELAY_SECONDS=None))


def test_fetch_retry_delay_negative_raises():
    with pytest.raises(ValueError, match="FETCH_RETRY_DELAY_SECONDS"):
        validate_config(_cfg(FETCH_RETRY_DELAY_SECONDS=-1))


def test_fetch_retry_delay_string_raises():
    with pytest.raises(ValueError, match="FETCH_RETRY_DELAY_SECONDS"):
        validate_config(_cfg(FETCH_RETRY_DELAY_SECONDS="60"))


def test_fetch_retry_delay_bool_raises():
    with pytest.raises(ValueError, match="FETCH_RETRY_DELAY_SECONDS"):
        validate_config(_cfg(FETCH_RETRY_DELAY_SECONDS=True))


# --- HEALTH_*_THRESHOLD ---


def test_health_failure_rate_threshold_zero_raises():
    with pytest.raises(ValueError, match="HEALTH_FAILURE_RATE_THRESHOLD"):
        validate_config(_cfg(HEALTH_FAILURE_RATE_THRESHOLD=0.0))


def test_health_count_drop_threshold_one_raises():
    with pytest.raises(ValueError, match="HEALTH_COUNT_DROP_THRESHOLD"):
        validate_config(_cfg(HEALTH_COUNT_DROP_THRESHOLD=1.0))


def test_health_threshold_non_float_raises():
    with pytest.raises(ValueError, match="HEALTH_FAILURE_RATE_THRESHOLD"):
        validate_config(_cfg(HEALTH_FAILURE_RATE_THRESHOLD=1))


def test_health_count_drop_threshold_non_float_raises():
    with pytest.raises(ValueError, match="HEALTH_COUNT_DROP_THRESHOLD"):
        validate_config(_cfg(HEALTH_COUNT_DROP_THRESHOLD=1))


# --- PRICE_ALERT_THRESHOLD ---


def test_price_alert_threshold_zero_raises():
    with pytest.raises(ValueError, match="PRICE_ALERT_THRESHOLD"):
        validate_config(_cfg(PRICE_ALERT_THRESHOLD=0))


def test_price_alert_threshold_negative_raises():
    with pytest.raises(ValueError, match="PRICE_ALERT_THRESHOLD"):
        validate_config(_cfg(PRICE_ALERT_THRESHOLD=-100))


def test_price_alert_threshold_bool_raises():
    with pytest.raises(ValueError, match="PRICE_ALERT_THRESHOLD"):
        validate_config(_cfg(PRICE_ALERT_THRESHOLD=True))


def test_price_alert_threshold_non_int_raises():
    with pytest.raises(ValueError, match="PRICE_ALERT_THRESHOLD"):
        validate_config(_cfg(PRICE_ALERT_THRESHOLD=49.99))


# --- PRICE_ALERT_THRESHOLD (dict form) ---


def test_price_alert_threshold_dict_valid_passes():
    validate_config(
        _cfg(
            PRICE_ALERT_THRESHOLD={
                ("CPH", "AMS"): 5000,
                ("AMS", "CPH"): 4500,
                "_default": 6000,
            }
        )
    )


def test_price_alert_threshold_dict_only_default_passes():
    validate_config(_cfg(PRICE_ALERT_THRESHOLD={"_default": 6000}))


def test_price_alert_threshold_dict_missing_default_raises():
    with pytest.raises(ValueError, match="PRICE_ALERT_THRESHOLD"):
        validate_config(_cfg(PRICE_ALERT_THRESHOLD={("CPH", "AMS"): 5000}))


def test_price_alert_threshold_dict_zero_value_raises():
    with pytest.raises(ValueError, match="PRICE_ALERT_THRESHOLD"):
        validate_config(
            _cfg(PRICE_ALERT_THRESHOLD={("CPH", "AMS"): 0, "_default": 6000})
        )


def test_price_alert_threshold_dict_negative_value_raises():
    with pytest.raises(ValueError, match="PRICE_ALERT_THRESHOLD"):
        validate_config(
            _cfg(PRICE_ALERT_THRESHOLD={("CPH", "AMS"): -100, "_default": 6000})
        )


def test_price_alert_threshold_dict_bool_value_raises():
    with pytest.raises(ValueError, match="PRICE_ALERT_THRESHOLD"):
        validate_config(
            _cfg(PRICE_ALERT_THRESHOLD={("CPH", "AMS"): True, "_default": 6000})
        )


# --- BACKUP_DIR ---


def test_backup_dir_none_raises():
    with pytest.raises(ValueError, match="BACKUP_DIR"):
        validate_config(_cfg(BACKUP_DIR=None))


def test_backup_dir_empty_string_raises():
    with pytest.raises(ValueError, match="BACKUP_DIR"):
        validate_config(_cfg(BACKUP_DIR=""))


def test_backup_dir_non_string_raises():
    with pytest.raises(ValueError, match="BACKUP_DIR"):
        validate_config(_cfg(BACKUP_DIR=42))


# --- BACKUP_KEEP_LAST_N ---


def test_backup_keep_last_n_none_raises():
    with pytest.raises(ValueError, match="BACKUP_KEEP_LAST_N"):
        validate_config(_cfg(BACKUP_KEEP_LAST_N=None))


def test_backup_keep_last_n_zero_raises():
    with pytest.raises(ValueError, match="BACKUP_KEEP_LAST_N"):
        validate_config(_cfg(BACKUP_KEEP_LAST_N=0))


def test_backup_keep_last_n_negative_raises():
    with pytest.raises(ValueError, match="BACKUP_KEEP_LAST_N"):
        validate_config(_cfg(BACKUP_KEEP_LAST_N=-1))


def test_backup_keep_last_n_bool_raises():
    with pytest.raises(ValueError, match="BACKUP_KEEP_LAST_N"):
        validate_config(_cfg(BACKUP_KEEP_LAST_N=True))


def test_backup_keep_last_n_float_raises():
    with pytest.raises(ValueError, match="BACKUP_KEEP_LAST_N"):
        validate_config(_cfg(BACKUP_KEEP_LAST_N=7.5))


def test_backup_keep_last_n_one_passes():
    validate_config(_cfg(BACKUP_KEEP_LAST_N=1))  # must not raise


# --- LOG_DIR ---


def test_log_dir_valid_passes():
    validate_config(_cfg(LOG_DIR="logs"))  # must not raise


def test_log_dir_empty_string_raises():
    with pytest.raises(ValueError, match="LOG_DIR"):
        validate_config(_cfg(LOG_DIR=""))


def test_log_dir_none_raises():
    with pytest.raises(ValueError, match="LOG_DIR"):
        validate_config(_cfg(LOG_DIR=None))


def test_log_dir_non_string_raises():
    with pytest.raises(ValueError, match="LOG_DIR"):
        validate_config(_cfg(LOG_DIR=42))


# --- LOG_KEEP_DAYS ---


def test_log_keep_days_valid_passes():
    validate_config(_cfg(LOG_KEEP_DAYS=14))  # must not raise


def test_log_keep_days_one_passes():
    validate_config(_cfg(LOG_KEEP_DAYS=1))  # must not raise


def test_log_keep_days_zero_raises():
    with pytest.raises(ValueError, match="LOG_KEEP_DAYS"):
        validate_config(_cfg(LOG_KEEP_DAYS=0))


def test_log_keep_days_negative_raises():
    with pytest.raises(ValueError, match="LOG_KEEP_DAYS"):
        validate_config(_cfg(LOG_KEEP_DAYS=-1))


def test_log_keep_days_string_raises():
    with pytest.raises(ValueError, match="LOG_KEEP_DAYS"):
        validate_config(_cfg(LOG_KEEP_DAYS="x"))


def test_log_keep_days_bool_raises():
    with pytest.raises(ValueError, match="LOG_KEEP_DAYS"):
        validate_config(_cfg(LOG_KEEP_DAYS=True))
