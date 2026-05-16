from datetime import date

from dateutil.relativedelta import relativedelta

import config
from src.date_generator import generate_target_dates


def test_returns_only_departure_weekdays():
    results = generate_target_dates(date.today())
    for d in results:
        assert d.weekday() in config.DEPARTURE_WEEKDAYS, (
            f"{d} is weekday {d.weekday()}, not in {config.DEPARTURE_WEEKDAYS}"
        )


def test_first_date_is_on_or_after_today():
    today = date.today()
    results = generate_target_dates(today)
    assert results[0] >= today


def test_last_date_is_within_six_months():
    today = date.today()
    cutoff = today + relativedelta(months=config.MAX_MONTHS_AHEAD)
    results = generate_target_dates(today)
    assert results[-1] <= cutoff


def test_list_is_sorted_ascending():
    results = generate_target_dates(date.today())
    assert results == sorted(results)


def test_no_duplicates():
    results = generate_target_dates(date.today())
    assert len(results) == len(set(results))


def test_known_date_range():
    # Use a fixed Monday as today; first result must be the Friday of that week.
    monday = date(2025, 9, 1)  # Monday
    results = generate_target_dates(monday)
    assert results[0] == date(2025, 9, 5)  # Friday


def test_today_included_when_it_is_a_departure_weekday():
    friday = date(2025, 9, 5)
    results = generate_target_dates(friday)
    assert friday in results
