def validate_config(cfg: dict) -> None:
    """Validate all tuneable config values. Raises ValueError with a clear message on any problem."""
    _check_routes(cfg.get("ROUTES"))
    _check_departure_weekdays(cfg.get("DEPARTURE_WEEKDAYS"))
    _check_max_months_ahead(cfg.get("MAX_MONTHS_AHEAD"))
    _check_max_stops(cfg.get("MAX_STOPS"))
    _check_window_hours(cfg.get("DAILY_WINDOW_START_HOUR"), cfg.get("DAILY_WINDOW_END_HOUR"))
    _check_database_path(cfg.get("DATABASE_PATH"))
    _check_price_alert_threshold(cfg.get("PRICE_ALERT_THRESHOLD"))


def _check_routes(routes) -> None:
    if not isinstance(routes, list) or len(routes) == 0:
        raise ValueError("ROUTES must be a non-empty list of (origin, destination) tuples")
    for route in routes:
        if not (isinstance(route, tuple) and len(route) == 2
                and isinstance(route[0], str) and isinstance(route[1], str)):
            raise ValueError(f"ROUTES: each route must be a (str, str) tuple, got {route!r}")
    if len(routes) != len(set(routes)):
        raise ValueError("ROUTES contains duplicate entries")


def _check_departure_weekdays(weekdays) -> None:
    if not isinstance(weekdays, list) or len(weekdays) == 0:
        raise ValueError("DEPARTURE_WEEKDAYS must be a non-empty list")
    for d in weekdays:
        if not isinstance(d, int) or not (0 <= d <= 6):
            raise ValueError(f"DEPARTURE_WEEKDAYS: each value must be an int 0–6, got {d!r}")


def _check_max_months_ahead(value) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError("MAX_MONTHS_AHEAD must be a positive integer")


def _check_max_stops(value) -> None:
    if value is None:
        raise ValueError("MAX_STOPS must be set (0 = nonstop)")
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError("MAX_STOPS must be an integer >= 0")


def _check_window_hours(start, end) -> None:
    for name, val in (("DAILY_WINDOW_START_HOUR", start), ("DAILY_WINDOW_END_HOUR", end)):
        if not isinstance(val, int) or not (0 <= val <= 23):
            raise ValueError(f"{name} must be an integer between 0 and 23, got {val!r}")
    if start >= end:
        raise ValueError(
            f"DAILY_WINDOW_START_HOUR ({start}) must be less than DAILY_WINDOW_END_HOUR ({end})"
        )


def _check_database_path(path) -> None:
    if not path or not isinstance(path, str):
        raise ValueError("DATABASE_PATH must be a non-empty string")


def _check_price_alert_threshold(value) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError("PRICE_ALERT_THRESHOLD must be a positive integer (price in cents)")
