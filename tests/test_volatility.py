from datetime import datetime, timedelta, timezone

import pytest

from src.insights.volatility import build_volatility


def _row(price_cents, days_before=14, retrieved=None, airline="KLM"):
    retrieved = retrieved or datetime(2026, 5, 15, tzinfo=timezone.utc)
    dep = (retrieved.date() + timedelta(days=days_before)).isoformat()
    return {
        "origin": "CPH",
        "destination": "AMS",
        "airline": airline,
        "retrieved_at": retrieved,
        "departure_date": dep,
        "price_cents": price_cents,
    }


def test_all_same_price_cv_zero():
    rows = [_row(500) for _ in range(5)]
    out = build_volatility(rows)
    b = out["buckets"][0]
    assert b["std_cents"] == 0
    assert b["cv"] == 0.0


def test_known_spread_cv_positive():
    rows = [_row(p) for p in [100, 200, 300, 400, 500]]
    out = build_volatility(rows)
    b = out["buckets"][0]
    assert b["std_cents"] > 0
    assert b["cv"] is not None and b["cv"] > 0


def test_zero_prices_cv_none():
    rows = [_row(0), _row(0), _row(0)]
    out = build_volatility(rows)
    b = out["buckets"][0]
    assert b["cv"] is None
    assert b["std_cents"] == 0


def test_sparse_bucket_omitted():
    rows = [_row(100), _row(200)]  # n=2
    out = build_volatility(rows)
    assert out["buckets"] == []


def test_empty_input():
    out = build_volatility([])
    assert out["buckets"] == []
