import os
import sys
from datetime import datetime
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.run_daily import _build_failure_summary, _maybe_send_failure_summary


def test_build_failure_summary_includes_breakdowns():
    failures_by_route = {"direct": 2, "proxy": 1}
    failures_by_kind = {
        "bot_challenge": 1,
        "rate_limited": 0,
        "parse_error": 0,
        "network": 0,
        "other": 2,
    }
    title, message, priority = _build_failure_summary(
        failures_by_route=failures_by_route,
        failures_by_kind=failures_by_kind,
        completed_jobs=5,
        total_jobs=10,
        now=datetime(2025, 1, 1, 18, 0),
    )
    assert "3 failures so far" in title
    assert "direct=2" in message
    assert "proxy=1" in message
    assert "bot challenge=1" in message
    assert "other=2" in message
    assert priority == "high"


def test_summary_not_sent_before_threshold_or_time():
    failures_by_route = {"direct": 3, "proxy": 0}
    failures_by_kind = {
        "bot_challenge": 0,
        "rate_limited": 0,
        "parse_error": 0,
        "network": 0,
        "other": 3,
    }
    with patch("scripts.run_daily.send_alert") as mock_alert:
        sent = _maybe_send_failure_summary(
            failures_by_route=failures_by_route,
            failures_by_kind=failures_by_kind,
            completed_jobs=3,
            total_jobs=10,
            now=datetime(2025, 1, 1, 17, 0),
            summary_sent=False,
        )
    assert sent is False
    mock_alert.assert_not_called()


def test_summary_sent_after_threshold_at_18():
    failures_by_route = {"direct": 4, "proxy": 1}
    failures_by_kind = {
        "bot_challenge": 0,
        "rate_limited": 1,
        "parse_error": 0,
        "network": 0,
        "other": 4,
    }
    with patch("scripts.run_daily.send_alert", return_value=True) as mock_alert:
        sent = _maybe_send_failure_summary(
            failures_by_route=failures_by_route,
            failures_by_kind=failures_by_kind,
            completed_jobs=6,
            total_jobs=10,
            now=datetime(2025, 1, 1, 18, 5),
            summary_sent=False,
        )
    assert sent is True
    mock_alert.assert_called_once()
