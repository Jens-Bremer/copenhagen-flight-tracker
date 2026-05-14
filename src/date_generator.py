from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

import config


def generate_target_dates(today: date) -> list[date]:
    """Return sorted list of dates from today through MAX_MONTHS_AHEAD that fall on DEPARTURE_WEEKDAYS."""
    cutoff = today + relativedelta(months=config.MAX_MONTHS_AHEAD)
    results = []
    current = today
    while current <= cutoff:
        if current.weekday() in config.DEPARTURE_WEEKDAYS:
            results.append(current)
        current += timedelta(days=1)
    return results
