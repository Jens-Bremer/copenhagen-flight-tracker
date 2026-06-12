from datetime import date, datetime, timedelta, timezone

import pytest

from src.insights.momentum import build_price_momentum


def _row(price_cents: int, retrieved: datetime, dep_offset_days: int = 30):
    dep = (retrieved.date() + timedelta(days=dep_offset_days)).isoformat()
    return {
        "origin": "CPH",
        "destination": "AMS",
        "airline": "KLM",
        "retrieved_at": retrieved,
        "departure_date": dep,
        "price_cents": price_cents,
    }


def _series(prices_per_day, start=date(2026, 5, 1), dep_offset_days=30):
    rows = []
    for i, price in enumerate(prices_per_day):
        ts = datetime.combine(start + timedelta(days=i), datetime.min.time(), tzinfo=timezone.utc)
        rows.append(_row(price, ts, dep_offset_days=dep_offset_days))
    return rows


def test_insufficient_history_emits_marker():
    # Only 3 distinct days < 14 → insufficient
    rows = _series([100, 110, 120])
    out = build_price_momentum(rows, now=datetime(2026, 5, 15, tzinfo=timezone.utc))
    assert out["insufficient_data"] == "need_min_14_days_history"
    assert out["routes"] == []
    assert out["history_days"] == 3


def test_falling_direction_over_7d():
    # 14 distinct days, strictly decreasing → falling
    prices = list(range(500, 360, -10))  # 14 values: 500..370
    rows = _series(prices)
    out = build_price_momentum(rows, now=datetime(2026, 6, 1, tzinfo=timezone.utc))
    r = out["routes"][0]
    assert r["recent_7d"]["direction"] == "falling"
    assert r["recent_7d"]["pct_change"] is not None and r["recent_7d"]["pct_change"] < 0


def test_rising_direction():
    prices = list(range(300, 440, 10))  # 14 values increasing
    rows = _series(prices)
    out = build_price_momentum(rows, now=datetime(2026, 6, 1, tzinfo=timezone.utc))
    assert out["routes"][0]["recent_14d"]["direction"] == "rising"


def test_flat_direction():
    prices = [400] * 14
    rows = _series(prices)
    out = build_price_momentum(rows, now=datetime(2026, 6, 1, tzinfo=timezone.utc))
    assert out["routes"][0]["recent_14d"]["direction"] == "flat"


def test_empty_input():
    out = build_price_momentum([], now=datetime(2026, 6, 1, tzinfo=timezone.utc))
    assert out["insufficient_data"] == "need_min_14_days_history"


def test_sweet_spot_picked_from_min_median():
    # 14 days history (so we pass the gate), with multiple lead-time buckets per row.
    rows = []
    start = date(2026, 5, 1)
    for i in range(14):
        ts = datetime.combine(start + timedelta(days=i), datetime.min.time(), tzinfo=timezone.utc)
        # 3 obs at db=10 cheap (~200), 3 obs at db=30 expensive (~500)
        rows.append(_row(200 + i, ts, dep_offset_days=10))
        rows.append(_row(500 + i, ts, dep_offset_days=30))
        rows.append(_row(210 + i, ts, dep_offset_days=10))
    out = build_price_momentum(rows, now=datetime(2026, 6, 1, tzinfo=timezone.utc))
    ss = out["routes"][0]["sweet_spot"]
    assert ss is not None
    # The cheap bucket median is ~205, expensive ~505 — sweet spot picks the 10-day bucket
    assert ss["days_before_low"] <= 10 <= ss["days_before_high"]
