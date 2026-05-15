"""Tests for src.frontend_csv_builder.

NOTE: All time fixtures in this file use the real prose format produced by
fast_flights (e.g. "7:30 PM on Fri, Jun 19"). Existing DB-layer tests use
simplified "08:00" strings, but those do not reflect what the scraper
actually returns and would mask real parse failures here.
"""

from datetime import datetime, timezone

import pytest

from src.frontend_csv_builder import parse_retrieved_at, parse_time_of_day


def test_parse_retrieved_at_floors_to_minute():
    result = parse_retrieved_at("2026-05-15T13:45:23.421566+00:00")
    assert result == datetime(2026, 5, 15, 13, 45, tzinfo=timezone.utc)


def test_parse_retrieved_at_already_at_minute():
    result = parse_retrieved_at("2026-05-15T13:45:00+00:00")
    assert result == datetime(2026, 5, 15, 13, 45, tzinfo=timezone.utc)


def test_parse_retrieved_at_rejects_naive_datetime():
    with pytest.raises(ValueError):
        parse_retrieved_at("2026-05-15T13:45:23")


def test_parse_retrieved_at_rejects_empty():
    with pytest.raises(ValueError):
        parse_retrieved_at("")


def test_parse_time_of_day_pm():
    assert parse_time_of_day("7:30 PM on Fri, Jun 19") == (19, 30)


def test_parse_time_of_day_am():
    assert parse_time_of_day("9:45 AM on Sat, Jun 20") == (9, 45)


def test_parse_time_of_day_noon():
    assert parse_time_of_day("12:00 PM on Fri, Jun 19") == (12, 0)


def test_parse_time_of_day_midnight():
    assert parse_time_of_day("12:00 AM on Sat, Jun 20") == (0, 0)


def test_parse_time_of_day_single_digit_hour():
    assert parse_time_of_day("3:25 PM on Fri, Jun 19") == (15, 25)


def test_parse_time_of_day_empty_raises():
    with pytest.raises(ValueError):
        parse_time_of_day("")


def test_parse_time_of_day_garbage_raises():
    with pytest.raises(ValueError):
        parse_time_of_day("sometime Fri")
