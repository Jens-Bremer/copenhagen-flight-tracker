from datetime import datetime
from unittest.mock import patch

from src.request_pacer import compute_sleep_intervals, seconds_until_window_start

WINDOW_START = 6
WINDOW_END = 22
WINDOW_SECONDS = (WINDOW_END - WINDOW_START) * 3600  # 57600

# Default mock time outside the window (e.g. 04:00) so that base = full window
FAKE_NOW_OUTSIDE = datetime(2025, 9, 5, 4, 0, 0)

# --- compute_sleep_intervals ---


@patch("src.request_pacer.datetime")
def test_one_request_returns_empty_list(mock_dt):
    mock_dt.now.return_value = FAKE_NOW_OUTSIDE
    assert compute_sleep_intervals(1, WINDOW_START, WINDOW_END) == []


@patch("src.request_pacer.datetime")
def test_returns_n_minus_one_intervals(mock_dt):
    mock_dt.now.return_value = FAKE_NOW_OUTSIDE
    intervals = compute_sleep_intervals(10, WINDOW_START, WINDOW_END)
    assert len(intervals) == 9


@patch("src.request_pacer.datetime")
def test_base_interval_is_window_divided_by_gaps(mock_dt):
    mock_dt.now.return_value = FAKE_NOW_OUTSIDE
    # With jitter removed (reproducible seed), intervals should cluster near base.
    base = WINDOW_SECONDS / 9  # ~6400s for 10 requests over 16 hours
    intervals = compute_sleep_intervals(10, WINDOW_START, WINDOW_END)
    for interval in intervals:
        assert max(120.0, base * 0.9) <= interval <= base * 1.1, (
            f"{interval} outside expected range"
        )


@patch("src.request_pacer.datetime")
def test_jitter_stays_within_ten_percent(mock_dt):
    mock_dt.now.return_value = FAKE_NOW_OUTSIDE
    base = WINDOW_SECONDS / 9
    for _ in range(20):  # run multiple times to catch unlucky seeds
        intervals = compute_sleep_intervals(10, WINDOW_START, WINDOW_END)
        for interval in intervals:
            assert max(120.0, base * 0.9) <= interval <= base * 1.1


@patch("src.request_pacer.datetime")
def test_all_intervals_are_positive(mock_dt):
    mock_dt.now.return_value = FAKE_NOW_OUTSIDE
    intervals = compute_sleep_intervals(10, WINDOW_START, WINDOW_END)
    assert all(i > 0 for i in intervals)


@patch("src.request_pacer.datetime")
def test_two_requests_returns_one_interval(mock_dt):
    mock_dt.now.return_value = FAKE_NOW_OUTSIDE
    intervals = compute_sleep_intervals(2, WINDOW_START, WINDOW_END)
    assert len(intervals) == 1
    base = WINDOW_SECONDS / 1
    assert max(120.0, base * 0.9) <= intervals[0] <= base * 1.1


@patch("src.request_pacer.datetime")
def test_inside_window_compresses_intervals(mock_dt):
    # Mock time to 14:00 (8 hours left in the 06:00-22:00 window)
    mock_dt.now.return_value = datetime(2025, 9, 5, 14, 0, 0)
    intervals = compute_sleep_intervals(10, WINDOW_START, WINDOW_END)
    base = (8 * 3600) / 9
    for interval in intervals:
        assert max(120.0, base * 0.9) <= interval <= base * 1.1


@patch("src.request_pacer.datetime")
def test_minimum_interval_is_120(mock_dt):
    # Mock time to 21:58 (2 minutes left, extremely tight)
    mock_dt.now.return_value = datetime(2025, 9, 5, 21, 58, 0)
    intervals = compute_sleep_intervals(10, WINDOW_START, WINDOW_END)
    for interval in intervals:
        assert interval >= 120.0


# --- seconds_until_window_start ---


def test_returns_zero_when_inside_window():
    # Mock now() to 10:00 — well within 06:00–22:00.
    fake_now = datetime(2025, 9, 5, 10, 0, 0)
    with patch("src.request_pacer.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        result = seconds_until_window_start(WINDOW_START)
    assert result == 0.0


def test_returns_zero_at_window_boundary():
    fake_now = datetime(2025, 9, 5, 6, 0, 0)
    with patch("src.request_pacer.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        result = seconds_until_window_start(WINDOW_START)
    assert result == 0.0


def test_returns_seconds_before_window():
    # Mock now() to 04:00 — 2 hours before the 06:00 window.
    fake_now = datetime(2025, 9, 5, 4, 0, 0)
    with patch("src.request_pacer.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        result = seconds_until_window_start(WINDOW_START)
    assert result == 2 * 3600


def test_returns_zero_when_past_window():
    # The function only receives window_start_hour, not window_end_hour.
    # Any time >= window_start is treated as "no wait needed" — cron handles
    # the overall scheduling so this case doesn't arise in practice.
    fake_now = datetime(2025, 9, 5, 23, 0, 0)
    with patch("src.request_pacer.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        result = seconds_until_window_start(WINDOW_START)
    assert result == 0.0
