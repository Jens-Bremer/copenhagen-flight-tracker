"""Tests for src/html_generator.py — frontend HTML generation from the slim CSV."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.html_generator import (
    build_analysis,
    build_calendar,
    build_flights,
    build_metadata,
    build_summary,
    generate,
    load_rows,
    render_html,
)

FIXTURE = Path(__file__).parent / "fixtures" / "flights_frontend_sample.csv"


def test_load_rows_returns_one_dict_per_csv_row():
    rows = load_rows(str(FIXTURE))
    assert len(rows) > 0
    assert all(isinstance(r, dict) for r in rows)


def test_load_rows_coerces_types():
    rows = load_rows(str(FIXTURE))
    row = rows[0]
    assert isinstance(row["retrieved_at"], datetime)  # tz-aware UTC
    assert row["retrieved_at"].tzinfo is not None
    assert isinstance(row["departure_date"], str)  # kept as ISO string
    assert isinstance(row["departure_at"], datetime)  # naive local
    assert row["departure_at"].tzinfo is None
    assert isinstance(row["arrival_at"], datetime)
    assert isinstance(row["duration_minutes"], int)
    assert isinstance(row["price_cents"], int)
    assert row["price_cents"] > 0


def test_load_rows_skips_blank_lines(tmp_path):
    csv_text = (
        "retrieved_at,departure_date,origin,destination,airline,"
        "departure_at,arrival_at,duration_minutes,price_cents,price_currency\n"
        "2026-05-15T13:45Z,2026-06-19,CPH,AMS,easyJet,"
        "2026-06-19T19:30:00,2026-06-19T21:00:00,90,9200,EUR\n"
        "\n"
    )
    p = tmp_path / "x.csv"
    p.write_text(csv_text)
    assert len(load_rows(str(p))) == 1


def test_load_rows_raises_on_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_rows(str(tmp_path / "nope.csv"))


def test_build_metadata_summarises_input_rows():
    rows = load_rows(str(FIXTURE))
    meta = build_metadata(
        rows, generated_at=datetime(2026, 5, 15, 23, 47, tzinfo=timezone.utc)
    )
    assert meta["generated_at"] == "2026-05-15T23:47Z"
    assert meta["total_rows"] == len(rows)
    assert meta["date_range"]["from"] <= meta["date_range"]["to"]
    assert "CPH-AMS" in meta["routes"]
    assert "AMS-CPH" in meta["routes"]
    assert "easyJet" in meta["airlines"]


def test_build_metadata_handles_empty_input():
    meta = build_metadata(
        [], generated_at=datetime(2026, 5, 15, 23, 47, tzinfo=timezone.utc)
    )
    assert meta["total_rows"] == 0
    assert meta["date_range"] == {"from": None, "to": None}
    assert meta["routes"] == []
    assert meta["airlines"] == []


def test_build_calendar_min_price_per_route_per_date():
    rows = load_rows(str(FIXTURE))
    cal = build_calendar(rows)
    # CPH-AMS 2026-06-19 has Ryanair at 7800 cents (cheapest)
    assert cal["CPH-AMS"]["2026-06-19"]["min_cents"] == 7800
    # flight_count = distinct (airline, dep_time) pairs across all retrieved_at
    assert cal["CPH-AMS"]["2026-06-19"]["flight_count"] >= 5


def test_build_calendar_empty_input():
    assert build_calendar([]) == {}


def test_build_calendar_separates_directions():
    rows = load_rows(str(FIXTURE))
    cal = build_calendar(rows)
    assert "CPH-AMS" in cal and "AMS-CPH" in cal
    # No CPH-AMS date should leak into AMS-CPH or vice versa
    overlap = set(cal["CPH-AMS"].keys()) & set(cal["AMS-CPH"].keys())
    # CPH-AMS dates and AMS-CPH dates are intentionally disjoint in the fixture
    assert len(overlap) == 0 or all(
        cal["CPH-AMS"][d]["min_cents"] != cal["AMS-CPH"][d]["min_cents"]
        for d in overlap
    )


def test_build_flights_returns_history_sorted_by_obs_date():
    rows = load_rows(str(FIXTURE))
    flights = build_flights(rows)
    # easyJet 19:30 on 2026-06-19 was observed 3 times (May 10/12/15) in the fixture
    easyjet = next(
        f
        for f in flights["CPH-AMS"]["2026-06-19"]
        if f["airline"] == "easyJet" and f["dep_time"] == "19:30"
    )
    assert len(easyjet["history"]) == 3
    dates = [h["obs_date"] for h in easyjet["history"]]
    assert dates == sorted(dates), "history must be chronological"
    assert easyjet["latest_cents"] == easyjet["history"][-1]["price_cents"]


def test_build_flights_overnight_flag():
    rows = load_rows(str(FIXTURE))
    flights = build_flights(rows)
    finnair = next(
        f for f in flights["CPH-AMS"]["2026-06-19"] if f["airline"] == "Finnair"
    )
    assert finnair["overnight"] is True
    assert finnair["duration_minutes"] == 945


def test_build_flights_days_before_per_observation():
    rows = load_rows(str(FIXTURE))
    flights = build_flights(rows)
    easyjet = next(
        f
        for f in flights["CPH-AMS"]["2026-06-19"]
        if f["airline"] == "easyJet" and f["dep_time"] == "19:30"
    )
    # 2026-05-10 retrieved_at → 2026-06-19 departure = 40 days
    assert easyjet["history"][0]["days_before"] == 40


def test_build_flights_empty_input():
    assert build_flights([]) == {}


def test_build_analysis_lead_time_curve_bins_by_days_before():
    rows = load_rows(str(FIXTURE))
    analysis = build_analysis(rows)
    curve = analysis["CPH-AMS"]["lead_time_curve"]
    # Every entry has the four required keys
    for entry in curve:
        assert {"days_before", "mean_cents", "min_cents", "obs_count"} <= entry.keys()
    # Sorted by days_before ascending
    assert [e["days_before"] for e in curve] == sorted(e["days_before"] for e in curve)


def test_build_analysis_sweet_spot_is_bucket_with_lowest_mean():
    rows = load_rows(str(FIXTURE))
    analysis = build_analysis(rows)
    cph_ams = analysis["CPH-AMS"]
    curve = cph_ams["lead_time_curve"]
    cheapest = min(curve, key=lambda e: e["mean_cents"])
    assert cph_ams["sweet_spot_days"] == cheapest["days_before"]


def test_build_analysis_day_of_week_has_seven_entries():
    rows = load_rows(str(FIXTURE))
    analysis = build_analysis(rows)
    dow = analysis["CPH-AMS"]["day_of_week"]
    # Only entries for days present in the data — but at least one
    assert 1 <= len(dow) <= 7
    for entry in dow:
        assert 0 <= entry["dow"] <= 6
        assert entry["label"] in {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}


def test_build_analysis_market_trend_is_sorted_by_obs_date():
    rows = load_rows(str(FIXTURE))
    analysis = build_analysis(rows)
    trend = analysis["CPH-AMS"]["market_trend"]
    dates = [t["obs_date"] for t in trend]
    assert dates == sorted(dates)


def test_build_analysis_empty_input():
    out = build_analysis([])
    assert out == {}


def test_build_summary_histogram_bin_width_500_cents():
    rows = load_rows(str(FIXTURE))
    summary = build_summary(rows)
    for route, blob in summary.items():
        for airline, bins in blob["histogram"].items():
            for b in bins:
                assert b["bin_high"] - b["bin_low"] == 500
                assert b["bin_low"] % 500 == 0
                assert b["count"] >= 1


def test_build_summary_weekend_pairs_join_fri_with_sun_plus_two():
    rows = load_rows(str(FIXTURE))
    summary = build_summary(rows)
    # CPH-AMS: outbound Fri = 2026-06-19, AMS-CPH inbound Sun = 2026-06-21
    pairs = summary["CPH-AMS"]["weekend_pairs"]
    assert len(pairs) >= 1
    pair = pairs[0]
    assert pair["fri_date"] == "2026-06-19"
    assert pair["sun_date"] == "2026-06-21"
    assert pair["total_cents"] == pair["fri_cents"] + pair["sun_cents"]
    # sorted ascending
    totals = [p["total_cents"] for p in pairs]
    assert totals == sorted(totals)
    assert len(pairs) <= 5


def test_build_summary_weekend_pairs_skip_when_inbound_missing(tmp_path):
    """No AMS-CPH observation for the joined Sunday → pair is dropped."""
    csv_text = (
        "retrieved_at,departure_date,origin,destination,airline,"
        "departure_at,arrival_at,duration_minutes,price_cents,price_currency\n"
        "2026-05-15T13:45Z,2026-06-19,CPH,AMS,easyJet,"
        "2026-06-19T19:30:00,2026-06-19T21:00:00,90,9200,EUR\n"
    )
    p = tmp_path / "x.csv"
    p.write_text(csv_text)
    rows = load_rows(str(p))
    summary = build_summary(rows)
    assert summary["CPH-AMS"]["weekend_pairs"] == []


def test_build_summary_empty_input():
    assert build_summary([]) == {}


def test_render_html_inlines_assets_and_data():
    html = render_html(
        metadata={"generated_at": "2026-05-15T23:47Z"},
        calendar={"CPH-AMS": {}},
        flights={"CPH-AMS": {}},
        analysis={"CPH-AMS": {}},
        summary={"CPH-AMS": {}},
    )
    # Asset inlining
    assert "<style>" in html
    assert "Theme port pending" in html or "--color-cream" in html
    assert "Chart.js" in html or "Chart=" in html or "chart.js" in html.lower()
    # JSON blobs are valid JSON inside <script> tags
    import re

    blobs = re.findall(
        r'<script type="application/json" id="(DATA_\w+)">(.*?)</script>', html, re.S
    )
    blob_dict = {k: v for k, v in blobs}
    assert set(blob_dict) == {
        "DATA_METADATA",
        "DATA_CALENDAR",
        "DATA_FLIGHTS",
        "DATA_ANALYSIS",
        "DATA_SUMMARY",
    }
    for raw in blob_dict.values():
        json.loads(raw)


def test_render_html_uses_safe_substitute_no_placeholder_leaks():
    html = render_html(
        metadata={},
        calendar={},
        flights={},
        analysis={},
        summary={},
    )
    # No raw ${...} markers should leak through
    assert "${INLINE_STYLES}" not in html
    assert "${DATA_METADATA}" not in html


def test_render_html_inlines_escapeHtml_helper():
    """app.js must inline an escapeHtml helper so attacker-controlled airline
    names cannot inject HTML via innerHTML/insertAdjacentHTML."""
    html = render_html(metadata={}, calendar={}, flights={}, analysis={}, summary={})
    assert "function escapeHtml" in html
    # And every site that interpolates an airline name should use it
    assert "escapeHtml(f.airline)" in html
    assert "escapeHtml(p.fri_airline)" in html
    assert "escapeHtml(p.sun_airline)" in html


def test_render_html_escapes_script_close_in_json_blobs():
    """A `</script>` byte sequence inside a string field must not break the JSON
    blob's enclosing <script> tag. The JSON serialiser substitutes `</` → `<\\/`,
    which JSON parses identically."""
    payload = {"airlines": ["KLM</script><script>alert(1)</script>"]}
    html = render_html(
        metadata=payload,
        calendar={},
        flights={},
        analysis={},
        summary={},
    )
    # Raw </script> must not appear inside the metadata blob
    import re

    m = re.search(
        r'<script type="application/json" id="DATA_METADATA">(.*?)</script>',
        html,
        re.S,
    )
    assert m, "DATA_METADATA blob not found"
    raw = m.group(1)
    # The dangerous byte sequence is the JSON-encoded literal `</`. After
    # escaping it becomes `<\/`, which the browser parses as JSON identically.
    assert "</script" not in raw
    assert "<\\/script" in raw
    # And the JSON still round-trips to the original payload
    assert json.loads(raw) == payload


def test_generate_writes_output_file(tmp_path):
    out_path = tmp_path / "index.html"
    n = generate(str(FIXTURE), str(out_path))
    assert n > 0
    assert out_path.exists()
    html = out_path.read_text(encoding="utf-8")
    assert "Copenhagen" in html
    assert '<script type="application/json" id="DATA_METADATA">' in html


def test_generate_missing_input_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        generate(str(tmp_path / "nope.csv"), str(tmp_path / "x.html"))


def test_generate_empty_input_writes_skeleton(tmp_path):
    p = tmp_path / "empty.csv"
    p.write_text(
        "retrieved_at,departure_date,origin,destination,airline,"
        "departure_at,arrival_at,duration_minutes,price_cents,price_currency\n"
    )
    out_path = tmp_path / "index.html"
    n = generate(str(p), str(out_path))
    assert n == 0
    html = out_path.read_text(encoding="utf-8")
    assert "Copenhagen" in html
    # DATA_METADATA contains total_rows=0
    assert '"total_rows":0' in html.replace(" ", "")


def test_cli_smoke(tmp_path):
    out = tmp_path / "index.html"
    result = subprocess.run(
        [
            "python3",
            "scripts/generate_html.py",
            "--input",
            str(FIXTURE),
            "--output",
            str(out),
        ],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parent.parent,
    )
    assert result.returncode == 0, result.stderr
    assert out.exists() and out.stat().st_size > 1024


def test_cli_missing_input_exits_2(tmp_path):
    out = tmp_path / "index.html"
    result = subprocess.run(
        [
            "python3",
            "scripts/generate_html.py",
            "--input",
            str(tmp_path / "nope.csv"),
            "--output",
            str(out),
        ],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parent.parent,
    )
    assert result.returncode == 2
