from datetime import datetime, timezone

import pytest

from src.insights.price_percentile import build_price_percentiles


def _row(price_cents: int, days_before: int, retrieved: datetime, airline: str = "KLM"):
    dep_date = retrieved.date().fromordinal(retrieved.date().toordinal() + days_before)
    return {
        "origin": "CPH",
        "destination": "AMS",
        "airline": airline,
        "retrieved_at": retrieved,
        "departure_date": dep_date.isoformat(),
        "price_cents": price_cents,
    }


def test_percentile_known_label_cheap():
    # Bucket [100,200,300,400,500] — latest is 200 (newest retrieved_at) → 25th → cheap
    base = datetime(2026, 6, 1, tzinfo=timezone.utc)
    rows = [
        _row(500, 14, datetime(2026, 5, 20, tzinfo=timezone.utc)),
        _row(400, 14, datetime(2026, 5, 22, tzinfo=timezone.utc)),
        _row(300, 14, datetime(2026, 5, 24, tzinfo=timezone.utc)),
        _row(100, 14, datetime(2026, 5, 26, tzinfo=timezone.utc)),
        _row(200, 14, datetime(2026, 5, 28, tzinfo=timezone.utc)),  # latest
    ]
    out = build_price_percentiles(rows, now=base, min_history_days=0)
    assert len(out["buckets"]) == 1
    b = out["buckets"][0]
    assert b["latest_price_cents"] == 200
    assert b["reference_n"] == 5
    assert b["percentile"] == pytest.approx(25.0)
    assert b["label"] == "cheap"


def test_percentile_label_expensive_at_75th():
    base = datetime(2026, 6, 1, tzinfo=timezone.utc)
    # Latest is 400 (75th) → expensive
    rows = [
        _row(100, 21, datetime(2026, 5, 20, tzinfo=timezone.utc)),
        _row(200, 21, datetime(2026, 5, 22, tzinfo=timezone.utc)),
        _row(300, 21, datetime(2026, 5, 24, tzinfo=timezone.utc)),
        _row(500, 21, datetime(2026, 5, 26, tzinfo=timezone.utc)),
        _row(400, 21, datetime(2026, 5, 28, tzinfo=timezone.utc)),  # latest, 75th
    ]
    out = build_price_percentiles(rows, now=base, min_history_days=0)
    assert out["buckets"][0]["label"] == "expensive"


def test_percentile_label_typical_middle():
    base = datetime(2026, 6, 1, tzinfo=timezone.utc)
    # [100,200,300,400,500] with latest=300 → 50th percentile → typical
    rows = [
        _row(100, 7, datetime(2026, 5, 20, tzinfo=timezone.utc)),
        _row(200, 7, datetime(2026, 5, 21, tzinfo=timezone.utc)),
        _row(400, 7, datetime(2026, 5, 22, tzinfo=timezone.utc)),
        _row(500, 7, datetime(2026, 5, 23, tzinfo=timezone.utc)),
        _row(300, 7, datetime(2026, 5, 24, tzinfo=timezone.utc)),  # latest
    ]
    out = build_price_percentiles(rows, now=base, min_history_days=0)
    assert out["buckets"][0]["label"] == "typical"
    assert out["buckets"][0]["percentile"] == pytest.approx(50.0)


def test_percentile_sparse_bucket_omitted():
    # n=2 < 3 → bucket dropped, no crash
    base = datetime(2026, 6, 1, tzinfo=timezone.utc)
    rows = [
        _row(100, 7, datetime(2026, 5, 20, tzinfo=timezone.utc)),
        _row(200, 7, datetime(2026, 5, 21, tzinfo=timezone.utc)),
    ]
    out = build_price_percentiles(rows, now=base, min_history_days=0)
    assert out["buckets"] == []


def test_empty_input():
    out = build_price_percentiles([], now=datetime(2026, 6, 1, tzinfo=timezone.utc))
    assert out["buckets"] == []
    assert out["min_samples"] == 3
    assert out["insufficient_data"] == "need_min_14_days_history"


def test_insufficient_history_marker():
    base = datetime(2026, 6, 1, tzinfo=timezone.utc)
    rows = [
        _row(100, 7, datetime(2026, 5, 20, tzinfo=timezone.utc)),
        _row(200, 7, datetime(2026, 5, 21, tzinfo=timezone.utc)),
        _row(300, 7, datetime(2026, 5, 22, tzinfo=timezone.utc)),
    ]
    out = build_price_percentiles(rows, now=base)  # default min_history_days=14
    assert out["insufficient_data"] == "need_min_14_days_history"
    assert out["buckets"] == []


def test_negative_days_before_dropped():
    base = datetime(2026, 6, 1, tzinfo=timezone.utc)
    # Departure was in the past relative to scrape → row dropped
    bad_row = {
        "origin": "CPH",
        "destination": "AMS",
        "airline": "KLM",
        "retrieved_at": datetime(2026, 6, 1, tzinfo=timezone.utc),
        "departure_date": "2026-05-01",
        "price_cents": 100,
    }
    out = build_price_percentiles([bad_row] * 5, now=base)
    assert out["buckets"] == []
