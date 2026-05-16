from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

import config


def generate_target_dates(today: date) -> list[date]:
    """Return dates falling on DEPARTURE_WEEKDAYS up to MAX_MONTHS_AHEAD, sorted."""
    cutoff = today + relativedelta(months=config.MAX_MONTHS_AHEAD)
    results = []
    current = today
    while current <= cutoff:
        if current.weekday() in config.DEPARTURE_WEEKDAYS:
            results.append(current)
        current += timedelta(days=1)
    return results
