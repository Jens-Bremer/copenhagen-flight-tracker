from datetime import datetime, timezone

import pytest

from src.insights.price_volatility_index import build_price_volatility_index

BASE_TIME = datetime(2026, 5, 15, tzinfo=timezone.utc)


def _row(price_cents, airline="KLM", obs_day=0, origin="CPH", destination="AMS"):
    retrieved = BASE_TIME.replace(day=1 + obs_day)
    return {
        "origin": origin,
        "destination": destination,
        "airline": airline,
        "retrieved_at": retrieved,
        "departure_date": "2026-07-01",
        "price_cents": price_cents,
    }


def _build(rows, **kwargs):
    return build_price_volatility_index(rows, now=BASE_TIME, **kwargs)


# ─── CV bars ─────────────────────────────────────────────────────────────────


def test_cv_bars_present_for_route():
    rows = [_row(p, obs_day=i % 3) for i, p in enumerate([100, 200, 300, 400, 500])]
    out = _build(rows, min_obs_for_cv=3, min_window_samples=2)
    assert "CPH-AMS" in out["by_route"]
    assert len(out["by_route"]["CPH-AMS"]["cv_bars"]) > 0


def test_cv_bars_sorted_descending_by_cv():
    rows = (
        [_row(p, airline="Norwegian", obs_day=i % 3) for i, p in enumerate([100, 500, 900, 100, 500])]
        + [_row(p, airline="KLM", obs_day=i % 3) for i, p in enumerate([200, 210, 205, 215, 208])]
    )
    out = _build(rows, min_obs_for_cv=3, min_window_samples=2)
    bars = out["by_route"]["CPH-AMS"]["cv_bars"]
    cvs = [b["cv"] for b in bars if b["cv"] is not None]
    assert cvs == sorted(cvs, reverse=True)


def test_cv_bar_fields():
    rows = [_row(p, obs_day=i % 3) for i, p in enumerate([100, 200, 300, 400, 500])]
    out = _build(rows, min_obs_for_cv=3, min_window_samples=2)
    bar = out["by_route"]["CPH-AMS"]["cv_bars"][0]
    assert {"airline", "cv", "mean_cents", "std_cents", "n"} <= bar.keys()
    assert bar["n"] >= 3
    assert bar["mean_cents"] > 0


def test_cv_bars_exclude_below_min_obs():
    # Only 2 rows for KLM, min is 3 → should be excluded.
    rows = [_row(100), _row(200)]
    out = _build(rows, min_obs_for_cv=3, min_window_samples=2)
    bars = out["by_route"]["CPH-AMS"]["cv_bars"]
    assert len(bars) == 0


def test_multi_airline_string_excluded():
    rows = [_row(p, airline="KLM,Air France", obs_day=i) for i, p in enumerate([100, 200, 300, 400, 500])]
    out = _build(rows, min_obs_for_cv=3, min_window_samples=2)
    # Route may not appear at all, or cv_bars is empty.
    route_data = out["by_route"].get("CPH-AMS", {})
    assert all(b["airline"] != "KLM,Air France" for b in route_data.get("cv_bars", []))


# ─── Rolling std dev ──────────────────────────────────────────────────────────


def test_rolling_stddev_fields():
    rows = [_row(p * 100, obs_day=i) for i, p in enumerate([10, 12, 11, 13, 10, 12, 11, 13, 12, 10])]
    out = _build(rows, min_obs_for_cv=3, min_window_samples=2)
    pts = out["by_route"]["CPH-AMS"]["rolling_stddev"]
    assert len(pts) > 0
    for pt in pts:
        assert {"airline", "obs_date", "stddev_cents", "daily_min_cents", "n"} <= pt.keys()
        assert pt["n"] >= 2
        assert pt["stddev_cents"] >= 0


def test_rolling_stddev_sorted_by_date():
    rows = [_row(p * 100, obs_day=i) for i, p in enumerate([10, 12, 11, 13, 10, 12, 11, 13, 12, 10])]
    out = _build(rows, min_obs_for_cv=3, min_window_samples=2)
    pts = out["by_route"]["CPH-AMS"]["rolling_stddev"]
    klm_pts = [p for p in pts if p["airline"] == "KLM"]
    dates = [p["obs_date"] for p in klm_pts]
    assert dates == sorted(dates)


def test_rolling_stddev_excluded_below_min_window():
    # Only 1 obs_date for KLM → no rolling point when min_window_samples=2.
    rows = [_row(100)]
    out = _build(rows, min_obs_for_cv=3, min_window_samples=2)
    pts = out["by_route"].get("CPH-AMS", {}).get("rolling_stddev", [])
    assert len(pts) == 0


# ─── Top-level schema ─────────────────────────────────────────────────────────


def test_top_level_schema():
    rows = [_row(p, obs_day=i % 3) for i, p in enumerate([100, 200, 300, 400, 500])]
    out = _build(rows, min_obs_for_cv=3, min_window_samples=2)
    assert "generated_at" in out
    assert "by_route" in out


def test_empty_rows():
    out = _build([])
    assert out["by_route"] == {}
