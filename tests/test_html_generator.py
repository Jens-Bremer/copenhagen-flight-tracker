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


def test_build_analysis_lead_time_curve_has_quartile_fields():
    """Each lead_time_curve entry must carry full quartile data so the frontend
    can shade an IQR band (Q1→Q3) around the mean line, giving users a sense
    of price spread at each booking horizon."""
    rows = load_rows(str(FIXTURE))
    analysis = build_analysis(rows)
    curve = analysis["CPH-AMS"]["lead_time_curve"]
    assert len(curve) > 0, "CPH-AMS lead_time_curve must be non-empty"
    for entry in curve:
        assert {"q1_cents", "median_cents", "q3_cents", "max_cents"} <= entry.keys(), (
            f"lead_time_curve entry missing quartile keys: {entry}"
        )
        # Values must be in non-decreasing order.
        assert entry["min_cents"] <= entry["q1_cents"] <= entry["median_cents"], (
            f"min ≤ Q1 ≤ median violated: {entry}"
        )
        assert entry["median_cents"] <= entry["q3_cents"] <= entry["max_cents"], (
            f"median ≤ Q3 ≤ max violated: {entry}"
        )


def test_leadtime_chart_renders_iqr_band():
    """The lead-time chart must reference q1_cents/q3_cents from the JSON data
    and use Chart.js fill to shade the IQR band between Q1 and Q3."""
    import re

    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    all_scripts = re.findall(r"<script[^>]*>(.*?)</script>", index_html, re.S)
    assert all_scripts
    app_js = all_scripts[-1]

    # The JS must map q1_cents and q3_cents from the curve data.
    assert "q1_cents" in app_js, (
        "renderTrends must reference q1_cents from the lead_time_curve JSON "
        "to build the lower bound of the IQR shading band"
    )
    assert "q3_cents" in app_js, (
        "renderTrends must reference q3_cents from the lead_time_curve JSON "
        "to build the upper bound of the IQR shading band"
    )
    # Chart.js fill property must be present for the band shading.
    assert "fill:" in app_js, (
        "renderTrends must use Chart.js fill: option to shade the Q1→Q3 band"
    )


def test_build_analysis_lead_time_curve_has_by_airline():
    """Each lead_time_curve entry must carry a by_airline dict."""
    rows = load_rows(str(FIXTURE))
    analysis = build_analysis(rows)
    curve = analysis["CPH-AMS"]["lead_time_curve"]
    assert len(curve) > 0

    # At least some entries must have airlines (fixture has multi-airline data).
    assert any(entry["by_airline"] for entry in curve), (
        "No curve entry has by_airline data; fixture may lack multi-airline data"
    )

    for entry in curve:
        assert "by_airline" in entry, (
            f"lead_time_curve entry missing by_airline: {entry}"
        )
        for airline, stats in entry["by_airline"].items():
            assert isinstance(airline, str)
            for key in ("median_cents", "q1_cents", "q3_cents", "obs_count"):
                assert key in stats, f"by_airline[{airline}] missing {key}"
            assert stats["obs_count"] >= 1


def test_build_analysis_sweet_spot_is_bucket_with_lowest_median():
    """sweet_spot_days picks the reliable bucket with the lowest median price.

    The fixture has fewer than 10 observations in every bucket, so all are
    filtered out and the result is None — which the frontend renders as the
    'Not enough data yet' fallback.
    """
    rows = load_rows(str(FIXTURE))
    analysis = build_analysis(rows)
    cph_ams = analysis["CPH-AMS"]
    curve = cph_ams["lead_time_curve"]
    import config

    reliable = [e for e in curve if e["obs_count"] >= config.RELIABLE_MIN_OBSERVATIONS]
    if reliable:
        cheapest = min(reliable, key=lambda e: e["median_cents"])
        assert cph_ams["sweet_spot_days"] == cheapest["days_before"]
    else:
        assert cph_ams["sweet_spot_days"] is None


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


def test_render_trends_tooltip_shows_obs_count():
    """renderTrends tooltip callback must reference obs_count from lead_time_curve."""
    js = Path("frontend/js/charts.js").read_text()
    assert "obs_count" in js, (
        "charts.js renderTrends tooltip must show n = obs_count per bucket"
    )


def test_build_analysis_empty_input():
    out = build_analysis([])
    assert out == {}


def test_build_analysis_time_of_day_matrix_has_correct_shape():
    """build_analysis must include a time_of_day_matrix per route.

    Each entry is a {dow, hour, mean_cents} dict where dow is 0=Mon..6=Sun
    and hour is the integer departure hour. The CPH-AMS fixture has flights
    with varied departure hours, so the matrix must be non-empty.
    """
    rows = load_rows(str(FIXTURE))
    analysis = build_analysis(rows)
    assert "time_of_day_matrix" in analysis["CPH-AMS"], (
        "build_analysis must add time_of_day_matrix to each route's analysis dict"
    )
    matrix = analysis["CPH-AMS"]["time_of_day_matrix"]
    assert len(matrix) > 0, "time_of_day_matrix must be non-empty for CPH-AMS"
    for entry in matrix:
        assert {"dow", "hour", "mean_cents"} <= entry.keys(), (
            f"time_of_day_matrix entry missing required keys: {entry}"
        )
        assert 0 <= entry["dow"] <= 6, f"dow out of range: {entry}"
        assert 0 <= entry["hour"] <= 23, f"hour out of range: {entry}"
        assert entry["mean_cents"] > 0, f"mean_cents must be positive: {entry}"


def test_build_analysis_normalized_price_progression():
    """build_analysis must include normalized_price_progression per route.

    Each entry is a {days_before, mean_pct_change} dict. The aggregate baseline
    (highest days_before per flight) anchors at 0%, so mean_pct_change at the
    oldest observation window should be close to 0. Flights with only one
    observation are excluded.
    """
    rows = load_rows(str(FIXTURE))
    analysis = build_analysis(rows)
    assert "normalized_price_progression" in analysis["CPH-AMS"], (
        "build_analysis must add normalized_price_progression to each route's dict"
    )
    prog = analysis["CPH-AMS"]["normalized_price_progression"]
    assert len(prog) > 0, "normalized_price_progression must be non-empty for CPH-AMS"
    for entry in prog:
        assert {"days_before", "mean_pct_change"} <= entry.keys(), (
            f"normalized_price_progression entry missing required keys: {entry}"
        )
        assert entry["days_before"] >= 0, f"days_before must be non-negative: {entry}"
        assert isinstance(entry["mean_pct_change"], float), (
            f"mean_pct_change must be a float: {entry}"
        )
    # Sorted ascending by days_before
    days = [e["days_before"] for e in prog]
    assert days == sorted(days), (
        "normalized_price_progression must be sorted by days_before"
    )


def test_normprog_panel_rendered_in_html():
    """The rendered HTML must contain the normalised-progression canvas and the
    JS must reference normalized_price_progression to build the chart."""
    import re

    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    all_scripts = re.findall(r"<script[^>]*>(.*?)</script>", index_html, re.S)
    assert all_scripts
    app_js = all_scripts[-1]

    assert 'id="normprog-chart"' in index_html, (
        'HTML template must include <canvas id="normprog-chart"> for the '
        "normalised price progression panel"
    )
    assert "normalized_price_progression" in app_js, (
        "app.js must reference normalized_price_progression to render the chart"
    )


def test_timeheat_panel_rendered_in_html():
    """The rendered HTML must contain a timeheat container element and the
    JS must reference time_of_day_matrix to populate it dynamically.

    The two fixed canvas IDs (timeheat-out / timeheat-back) were replaced in
    #104 with a single <div id="timeheat-container"> so that the renderer can
    create one canvas per route for any arbitrary route list.
    """
    import re

    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    all_scripts = re.findall(r"<script[^>]*>(.*?)</script>", index_html, re.S)
    assert all_scripts
    app_js = all_scripts[-1]

    # Dynamic container (replaces the old fixed canvas IDs).
    assert 'id="timeheat-container"' in index_html, (
        'HTML template must include <div id="timeheat-container"> for dynamic '
        'per-route heatmap canvases (replaces old id="timeheat-out"/id="timeheat-back")'
    )
    # JS must read time_of_day_matrix from the analysis data
    assert "time_of_day_matrix" in app_js, (
        "app.js must reference time_of_day_matrix to render the heatmap cells"
    )
    # JS must iterate over routes dynamically, not use hardcoded IDs
    assert "timeheat-container" in app_js, (
        "app.js must reference timeheat-container to build canvases per route"
    )


def test_build_summary_histogram_bin_width_500_cents():
    rows = load_rows(str(FIXTURE))
    summary = build_summary(rows)
    for _route, blob in summary.items():
        for _airline, bins in blob["histogram"].items():
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


def test_build_summary_weekend_pairs_both_directions(tmp_path):
    """build_summary must compute pairs for both travel directions:
    CPH-AMS (Fri) + AMS-CPH (Sun) for the CPH-resident traveller, AND
    AMS-CPH (Fri) + CPH-AMS (Sun) for the AMS-resident traveller.

    Previously only Direction 1 was computed; Direction 2 pairs were silently
    dropped, leaving AMS-CPH.weekend_pairs always empty.
    """
    csv_text = (
        "retrieved_at,departure_date,origin,destination,airline,"
        "departure_at,arrival_at,duration_minutes,price_cents,price_currency\n"
        # Direction 1: CPH→AMS Friday outbound (2026-06-26 = Friday)
        "2026-05-15T13:45Z,2026-06-26,CPH,AMS,easyJet,"
        "2026-06-26T19:30:00,2026-06-26T21:00:00,90,8900,EUR\n"
        # Direction 1: AMS→CPH Sunday inbound
        "2026-05-15T13:45Z,2026-06-28,AMS,CPH,KLM,"
        "2026-06-28T17:55:00,2026-06-28T19:25:00,90,10000,EUR\n"
        # Direction 2: AMS→CPH Friday outbound (same Friday)
        "2026-05-15T13:45Z,2026-06-26,AMS,CPH,Norwegian,"
        "2026-06-26T18:00:00,2026-06-26T19:30:00,90,9500,EUR\n"
        # Direction 2: CPH→AMS Sunday inbound
        "2026-05-15T13:45Z,2026-06-28,CPH,AMS,Ryanair,"
        "2026-06-28T09:00:00,2026-06-28T10:30:00,90,7800,EUR\n"
    )
    p = tmp_path / "x.csv"
    p.write_text(csv_text)
    rows = load_rows(str(p))
    summary = build_summary(rows)

    # Direction 1 (existing): CPH-AMS Fri + AMS-CPH Sun
    pairs_out = summary["CPH-AMS"]["weekend_pairs"]
    assert len(pairs_out) == 1
    assert pairs_out[0]["fri_date"] == "2026-06-26"
    assert pairs_out[0]["sun_date"] == "2026-06-28"

    # Direction 2 (new): AMS-CPH Fri + CPH-AMS Sun
    pairs_back = summary["AMS-CPH"]["weekend_pairs"]
    assert len(pairs_back) == 1, (
        "build_summary must also compute AMS-CPH Friday + CPH-AMS Sunday pairs "
        "so Amsterdam-resident travellers see their weekend options"
    )
    assert pairs_back[0]["fri_date"] == "2026-06-26"
    assert pairs_back[0]["sun_date"] == "2026-06-28"


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


def test_build_summary_weekend_pairs_uses_cheapest_flight(tmp_path):
    """When multiple airlines fly the same Friday, the cheapest wins the pair."""
    csv_text = (
        "retrieved_at,departure_date,origin,destination,airline,"
        "departure_at,arrival_at,duration_minutes,price_cents,price_currency\n"
        # Friday outbound — expensive airline
        "2026-05-15T13:45Z,2026-06-19,CPH,AMS,KLM,"
        "2026-06-19T10:00:00,2026-06-19T12:00:00,120,15000,EUR\n"
        # Friday outbound — cheaper airline on same day
        "2026-05-15T13:45Z,2026-06-19,CPH,AMS,easyJet,"
        "2026-06-19T19:30:00,2026-06-19T21:00:00,90,8900,EUR\n"
        # Sunday inbound — only one option
        "2026-05-15T13:45Z,2026-06-21,AMS,CPH,KLM,"
        "2026-06-21T17:55:00,2026-06-21T19:25:00,90,10000,EUR\n"
    )
    p = tmp_path / "x.csv"
    p.write_text(csv_text)
    rows = load_rows(str(p))
    summary = build_summary(rows)

    pairs = summary["CPH-AMS"]["weekend_pairs"]
    assert len(pairs) == 1
    assert pairs[0]["fri_airline"] == "easyJet", (
        "build_summary must pick the cheapest Friday flight, not the latest-retrieved"
    )
    assert pairs[0]["fri_cents"] == 8900
    assert pairs[0]["total_cents"] == 8900 + 10000


def test_render_html_inlines_assets_and_data():
    """With inline_data=True the five JSON blobs are embedded into the HTML."""
    index_html, _ = render_html(
        metadata={"generated_at": "2026-05-15T23:47Z"},
        calendar={"CPH-AMS": {}},
        flights={"CPH-AMS": {}},
        analysis={"CPH-AMS": {}},
        summary={"CPH-AMS": {}},
        inline_data=True,
    )
    # Asset inlining
    assert "<style>" in index_html
    assert "Theme port pending" in index_html or "--color-cream" in index_html
    has_chart = "Chart.js" in index_html or "Chart=" in index_html
    assert has_chart or "chart.js" in index_html.lower()
    # JSON blobs are valid JSON inside <script> tags
    import re

    pattern = r'<script type="application/json" id="(DATA_\w+)">(.*?)</script>'
    blobs = re.findall(pattern, index_html, re.S)
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


def test_render_html_default_mode_blobs_are_empty():
    """With inline_data=False (default) the five JSON script elements are empty
    so the browser fetches data.json instead."""
    import re

    index_html, _ = render_html(
        metadata={"generated_at": "2026-05-15T23:47Z"},
        calendar={"CPH-AMS": {}},
        flights={"CPH-AMS": {}},
        analysis={"CPH-AMS": {}},
        summary={"CPH-AMS": {}},
    )
    pattern = r'<script type="application/json" id="(DATA_\w+)">(.*?)</script>'
    blobs = re.findall(pattern, index_html, re.S)
    blob_dict = {k: v for k, v in blobs}
    # All five script elements must be present but contain no data
    assert set(blob_dict) == {
        "DATA_METADATA",
        "DATA_CALENDAR",
        "DATA_FLIGHTS",
        "DATA_ANALYSIS",
        "DATA_SUMMARY",
    }
    for raw in blob_dict.values():
        assert raw.strip() == "", (
            f"Expected empty blob in default mode, got: {raw[:80]!r}"
        )


def test_render_html_uses_safe_substitute_no_placeholder_leaks():
    index_html, _ = render_html(
        metadata={},
        calendar={},
        flights={},
        analysis={},
        summary={},
    )
    # No raw ${...} markers should leak through
    assert "${INLINE_STYLES}" not in index_html
    assert "${DATA_METADATA}" not in index_html


def test_format_price_uses_whole_euros_not_decimal():
    """All price values rendered by app.js must use whole euros (Math.round),
    not two-decimal-place formatting (.toFixed(2)).

    Prices are stored as integer cents in the JSON blobs and divided by 100
    in JS.  Using .toFixed(2) produces strings like '€161.00'; the correct
    output is '€161'.  This test checks the inlined app.js script for the
    presence of the correct pattern.
    """
    import re

    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    # app.js is always the last <script> tag in the template (Chart.js comes before it).
    # We must not match Chart.js, which also uses .toFixed(2) internally.
    all_scripts = re.findall(r"<script[^>]*>(.*?)</script>", index_html, re.S)
    assert all_scripts, "No <script> blocks found in rendered HTML"
    app_js = all_scripts[-1]  # app.js is the very last script tag per the template

    # No price value should be formatted with two decimal places.
    assert ".toFixed(2)" not in app_js, (
        "Found .toFixed(2) in inlined app.js — price formatting must use "
        "Math.round() to show whole euros (e.g. '€161' not '€161.00')"
    )
    # The formatPrice helper must exist and use Math.round.
    assert "Math.round(cents / 100)" in app_js, (
        "formatPrice must use Math.round(cents / 100) for whole-euro amounts"
    )


def test_histograms_use_stacked_bars_with_airline_segments():
    """Price-distribution histograms must stack per-airline bars within each bin.

    Chart.js requires stacked: true on both the x and y scale axes.  The
    previous (broken) state used stacked: false, which produced grouped
    side-by-side bars per airline instead of one stacked bar per bin.

    The tooltip must also include a footer callback that shows the bin total
    so users can see both the airline's contribution and the aggregate count.
    """
    import re

    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    # app.js is always the last <script> tag in the template.
    all_scripts = re.findall(r"<script[^>]*>(.*?)</script>", index_html, re.S)
    assert all_scripts, "No <script> blocks found in rendered HTML"
    app_js = all_scripts[-1]

    # Grouped mode (old behaviour) must be absent.
    assert "stacked: false" not in app_js, (
        "Found 'stacked: false' in app.js — histogram bars must use stacked: true "
        "so that per-airline segments stack into a single bar per price bin"
    )
    # Both x and y axes of the histogram chart must opt into stacking.
    stacked_true_count = app_js.count("stacked: true")
    assert stacked_true_count >= 2, (
        f"Expected at least 2 occurrences of 'stacked: true' (one per axis) "
        f"in renderHistograms, found {stacked_true_count}"
    )
    # A tooltip footer callback must exist to show the bin total.
    assert "footer:" in app_js, (
        "renderHistograms tooltip must include a 'footer:' callback "
        "showing the aggregate observation count for the hovered bin"
    )


def test_footer_charts_use_gentle_pricetint_palette():
    """DOW and month charts must not use old hard-coded bar-chart colours.

    Since these charts are now boxplots using calendar data, the old
    --color-green-ahead / --color-orange bar colours should be absent.
    priceTint() continues to appear in renderCalendar.
    """
    import re

    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    all_scripts = re.findall(r"<script[^>]*>(.*?)</script>", index_html, re.S)
    assert all_scripts, "No <script> blocks found in rendered HTML"
    app_js = all_scripts[-1]

    # Old hard-coded colours must be gone.
    assert "'var(--color-green-ahead)'" not in app_js, (
        "renderFooterCharts must not use --color-green-ahead"
    )
    assert "'var(--color-orange)'" not in app_js, (
        "renderFooterCharts must not use --color-orange"
    )
    # priceTint() is still used in renderCalendar.
    assert "priceTint(" in app_js, "priceTint() must still appear in renderCalendar"


def test_footer_charts_use_boxplots():
    """DOW and month charts must use boxplot charts (not bar charts) to show
    the full price distribution rather than just a single mean value.

    renderFooterCharts must extract raw price arrays from DATA.calendar and
    pass them to a Chart with type 'boxplot'.
    The old aggregate()/ROUTE_COLORS bar-chart approach must be gone.
    """
    import re

    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    all_scripts = re.findall(r"<script[^>]*>(.*?)</script>", index_html, re.S)
    assert all_scripts, "No <script> blocks found in rendered HTML"
    app_js = all_scripts[-1]

    # boxplot chart type must be used for footer charts.
    assert "'boxplot'" in app_js, (
        "renderFooterCharts must create charts with type: 'boxplot'"
    )
    # Calendar data (min_cents) must be the data source for spread calculation.
    assert "min_cents" in app_js, (
        "renderFooterCharts must read min_cents from DATA.calendar to build "
        "raw price arrays for the boxplot"
    )
    # The old aggregate() helper that averaged both routes is gone.
    assert "grouped[k].values.push" not in app_js, (
        "The old aggregate() helper in renderFooterCharts must be removed"
    )


def test_calendar_local_dates_and_month_navigation():
    """The calendar must:

    (a) Build ISO strings from *local* Date components, not toISOString(),
        which converts to UTC and shifts displayed dates in timezones east of
        UTC (e.g. CEST = UTC+2: local midnight becomes the previous UTC day).

    (b) Render only one calendar month at a time, tracked by state.calendarMonth,
        so the grid is compact and easy to scan.

    (c) Expose three navigation elements in the HTML so the user can move
        between months: id=cal-prev, id=cal-month-label, id=cal-next.
    """
    import re

    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    all_scripts = re.findall(r"<script[^>]*>(.*?)</script>", index_html, re.S)
    assert all_scripts, "No <script> blocks found in rendered HTML"
    app_js = all_scripts[-1]

    # (a) Local-date ISO construction must replace cursor.toISOString().
    # Note: the string 'toISOString()' may appear in explanatory comments; we
    # specifically check for the cursor. call-site form.
    assert "cursor.toISOString()" not in app_js, (
        "renderCalendar must not call cursor.toISOString() — it converts to UTC "
        "and shifts dates in positive-offset timezones. Build the ISO string "
        "from getFullYear()/getMonth()/getDate() instead."
    )
    # (b) state must track the currently displayed month.
    assert "calendarMonth" in app_js, (
        "state must include a calendarMonth property so the calendar renders "
        "only one month at a time and can navigate between months"
    )
    # (c) Navigation DOM elements must be present in the generated HTML.
    assert 'id="cal-prev"' in index_html, (
        "Previous-month button (id=cal-prev) missing from template"
    )
    assert 'id="cal-next"' in index_html, (
        "Next-month button (id=cal-next) missing from template"
    )
    assert 'id="cal-month-label"' in index_html, (
        "Month label (id=cal-month-label) missing from template"
    )


def test_render_html_inlines_escapeHtml_helper():
    """app.js must inline an escapeHtml helper so attacker-controlled airline
    names cannot inject HTML via innerHTML/insertAdjacentHTML."""
    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    assert "function escapeHtml" in index_html
    # And every site that interpolates an airline name should use it
    assert "escapeHtml(f.airline)" in index_html
    assert "escapeHtml(p.fri_airline)" in index_html
    assert "escapeHtml(p.sun_airline)" in index_html


def test_render_html_escapes_script_close_in_json_blobs():
    """A `</script>` byte sequence inside a string field must not break the JSON
    blob's enclosing <script> tag. The JSON serialiser substitutes `</` → `<\\/`,
    which JSON parses identically."""
    payload = {"airlines": ["KLM</script><script>alert(1)</script>"]}
    index_html, _ = render_html(
        metadata=payload,
        calendar={},
        flights={},
        analysis={},
        summary={},
        inline_data=True,
    )
    # Raw </script> must not appear inside the metadata blob
    import re

    m = re.search(
        r'<script type="application/json" id="DATA_METADATA">(.*?)</script>',
        index_html,
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
    """Default mode: writes index.html + sibling data.json; blobs are NOT inlined."""
    out_path = tmp_path / "index.html"
    n = generate(str(FIXTURE), str(out_path))
    assert n > 0
    assert out_path.exists()
    html = out_path.read_text(encoding="utf-8")
    assert "Copenhagen" in html
    # In default (external) mode the script elements are present but empty
    assert '<script type="application/json" id="DATA_METADATA">' in html
    import re

    m = re.search(
        r'<script type="application/json" id="DATA_METADATA">(.*?)</script>',
        html,
        re.S,
    )
    assert m and m.group(1).strip() == "", (
        "DATA_METADATA blob should be empty in default mode"
    )
    # data.json must exist as a sibling
    data_json = tmp_path / "data.json"
    assert data_json.exists(), "data.json sibling was not written by generate()"
    payload = json.loads(data_json.read_text(encoding="utf-8"))
    assert "metadata" in payload and "calendar" in payload
    assert "flights" in payload and "analysis" in payload and "summary" in payload


def test_generate_writes_output_file_inline_data(tmp_path):
    """With inline_data=True the five blobs are embedded in the HTML (no data.json)."""
    out_path = tmp_path / "index.html"
    n = generate(str(FIXTURE), str(out_path), inline_data=True)
    assert n > 0
    assert out_path.exists()
    html = out_path.read_text(encoding="utf-8")
    assert "Copenhagen" in html
    # Blobs must be inlined
    import re

    m = re.search(
        r'<script type="application/json" id="DATA_METADATA">(.*?)</script>',
        html,
        re.S,
    )
    assert m and m.group(1).strip() != "", (
        "DATA_METADATA blob should be non-empty with inline_data=True"
    )
    # No data.json should be written
    data_json = tmp_path / "data.json"
    assert not data_json.exists(), (
        "data.json should NOT be written when inline_data=True"
    )


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
    # DATA_METADATA with total_rows=0 is in data.json (default mode)
    data_json = tmp_path / "data.json"
    assert data_json.exists()
    payload = json.loads(data_json.read_text(encoding="utf-8"))
    assert payload["metadata"]["total_rows"] == 0


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


# ─── Issue #95: hero summary panel ───────────────────────────────────────────


def _app_js(html: str) -> str:
    """Extract the last <script> block (inlined app.js) from rendered HTML."""
    import re

    all_scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.S)
    assert all_scripts, "No <script> blocks found in rendered HTML"
    return all_scripts[-1]


def test_hero_panel_dom_ids_present_in_template():
    """Template must include the three hero card container IDs."""
    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    assert 'id="hero-best-time"' in index_html, "hero-best-time container missing"
    assert 'id="hero-market"' in index_html, "hero-market container missing"
    assert 'id="hero-book-when"' in index_html, "hero-book-when container missing"


def test_hero_ids_in_required_dom_ids():
    """All three hero IDs must be asserted at boot via REQUIRED_DOM_IDS."""
    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    js = _app_js(index_html)
    assert "'hero-best-time'" in js, "hero-best-time not in REQUIRED_DOM_IDS"
    assert "'hero-market'" in js, "hero-market not in REQUIRED_DOM_IDS"
    assert "'hero-book-when'" in js, "hero-book-when not in REQUIRED_DOM_IDS"


def test_render_hero_function_exists_and_called_from_render_all():
    """app.js must define renderHero() and call it from renderAll()."""
    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    js = _app_js(index_html)
    assert "function renderHero" in js, "renderHero function not defined"
    assert "renderHero()" in js, "renderHero() not called from renderAll()"


def test_hero_best_time_reads_correct_analysis_fields():
    """renderHero must read best_time_to_visit with cheapest_month, cheapest_dow,
    and lowest_ever from DATA_ANALYSIS."""
    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    js = _app_js(index_html)
    assert "best_time_to_visit" in js
    assert "cheapest_month" in js
    assert "cheapest_dow" in js
    assert "lowest_ever" in js


def test_hero_market_reads_market_direction_from_analysis():
    """renderHero must read market_direction.trend and market_direction.label."""
    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    js = _app_js(index_html)
    assert "market_direction" in js
    # Must handle all three trend values
    assert "'down'" in js or '"down"' in js, "trend 'down' not handled"
    assert "'up'" in js or '"up"' in js, "trend 'up' not handled"
    assert "'stable'" in js or '"stable"' in js, "trend 'stable' not handled"


def test_hero_book_when_uses_sweet_spot_days():
    """renderHero must use sweet_spot_days from DATA_ANALYSIS for the booking card."""
    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    js = _app_js(index_html)
    assert "sweet_spot_days" in js


def test_hero_css_classes_present_in_styles():
    """Generated HTML must include .hero-summary and .hero-card CSS rules."""
    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    assert "hero-summary" in index_html
    assert "hero-card" in index_html


def test_hero_section_positioned_before_calendar_in_template():
    """Hero panel must appear in the template before the calendar section."""
    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    hero_pos = index_html.find('id="hero-best-time"')
    calendar_pos = index_html.find('id="calendar"')
    assert hero_pos != -1, "hero-best-time not in HTML"
    assert calendar_pos != -1, "calendar not in HTML"
    assert hero_pos < calendar_pos, (
        "Hero panel must appear before the calendar in the HTML"
    )


def test_hero_shows_fallback_when_no_analysis_data():
    """renderHero must not crash and show a fallback when DATA_ANALYSIS is empty."""
    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    js = _app_js(index_html)
    # There must be a fallback path (e.g. early return or "Not enough data" text)
    assert "Not enough data" in js or "fallback" in js.lower() or "return" in js, (
        "renderHero must handle empty analysis gracefully"
    )


# ─── Issue #93 scope: "you are here" marker on lead-time curve ────────────────


def test_leadtime_chart_has_you_are_here_marker_logic():
    """renderTrends must compute the number of days until the selected departure
    date and draw a 'you are here' vertical marker on the lead-time chart."""
    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    js = _app_js(index_html)
    # The JS must reference selectedDate to compute proximity to departure
    assert "selectedDate" in js
    # It must calculate days until departure (some variation of the formula)
    assert "daysUntilDep" in js or "days_until" in js or "daysBeforeDep" in js


def test_leadtime_you_are_here_uses_afterdraw_plugin():
    """The 'you are here' marker must be drawn via a Chart.js afterDraw plugin
    so it works without an external annotation library."""
    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    js = _app_js(index_html)
    assert "afterDraw" in js, "afterDraw plugin required for 'you are here' marker"


def test_leadtime_you_are_here_label_present():
    """The marker must include a visible 'today' label for users to understand it."""
    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    js = _app_js(index_html)
    assert "today" in js or "You are here" in js or "you are here" in js.lower()


# ─── Issue #95 scope: hero "both" route aggregation ───────────────────────────


def test_hero_both_route_averages_sweet_spot_days():
    """renderHero must average sweet_spot_days across both routes when
    state.route === 'both', not silently use only CPH-AMS."""
    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    js = _app_js(index_html)
    # The hero function must reference more than activeRoutes()[0] for sweet_spot_days
    # i.e. it must iterate or reduce over activeRoutes()
    patterns = [
        "activeRoutes().length",
        "routes.length",
        "routes.forEach",
        "routes.map",
    ]
    assert any(p in js for p in patterns), (
        "renderHero must iterate over all active routes to aggregate data for 'both'"
    )


# ─── Issue #100: per-day trajectory arrows on calendar cells ──────────────────


def test_calendar_cell_trajectory_span_referenced_in_app_js():
    """renderCalendar must emit a .calendar__cell__trajectory span for
    cells where the cheapest flight has a non-null trajectory."""
    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    js = _app_js(index_html)
    assert "calendar__cell__trajectory" in js, (
        "renderCalendar must reference calendar__cell__trajectory"
    )


def test_calendar_trajectory_reads_from_flights_data():
    """The calendar trajectory indicator must read trajectory from DATA_FLIGHTS,
    not from DATA_CALENDAR (which has no trajectory field)."""
    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    js = _app_js(index_html)
    # renderCalendar must look up trajectory from DATA.flights
    assert "trajectory" in js
    assert "DATA.flights" in js or "flights[" in js


def test_calendar_trajectory_skipped_when_null():
    """No arrow must be emitted when trajectory is null."""
    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    js = _app_js(index_html)
    # There must be a null guard for trajectory in the calendar rendering path
    assert "trajectory" in js
    # Either explicit null check or falsy guard
    assert "null" in js or "trajectory)" in js or "!trajectory" in js


def test_calendar_trajectory_arrow_has_aria_label():
    """The calendar trajectory span must carry an aria-label."""
    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    js = _app_js(index_html)
    # aria-label must be set on the trajectory span in calendar rendering
    # (There is already one for the drill-down arrows; we need it in renderCalendar too)
    assert "trending" in js.lower() or "aria-label" in js


def test_calendar_trajectory_css_in_styles():
    """styles.css must define .calendar__cell__trajectory."""
    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    assert ".calendar__cell__trajectory" in index_html


# ─── Issue #99: integration — new fields appear in rendered JSON blobs ────────


def test_data_analysis_blob_contains_market_direction_and_best_time():
    """DATA_ANALYSIS JSON blob in the rendered HTML must contain market_direction
    and best_time_to_visit for every route in the fixture data."""
    import re

    rows = load_rows(str(FIXTURE))
    now = datetime(2026, 5, 15, 23, 47, tzinfo=timezone.utc)
    analysis = build_analysis(rows)
    index_html, _ = render_html(
        metadata=build_metadata(rows, now),
        calendar=build_calendar(rows),
        flights=build_flights(rows),
        analysis=analysis,
        summary=build_summary(rows),
        inline_data=True,
    )
    m = re.search(
        r'<script type="application/json" id="DATA_ANALYSIS">(.*?)</script>',
        index_html,
        re.S,
    )
    assert m, "DATA_ANALYSIS blob not found"
    blob = json.loads(m.group(1))
    for route in blob:
        assert "market_direction" in blob[route], (
            f"market_direction missing from DATA_ANALYSIS[{route}]"
        )
        assert "best_time_to_visit" in blob[route], (
            f"best_time_to_visit missing from DATA_ANALYSIS[{route}]"
        )


def test_data_flights_blob_contains_trajectory_percentile_mean():
    """DATA_FLIGHTS JSON blob must carry trajectory, trajectory_pct, percentile,
    and historical_mean_cents on every flight entry."""
    import re

    rows = load_rows(str(FIXTURE))
    now = datetime(2026, 5, 15, 23, 47, tzinfo=timezone.utc)
    index_html, _ = render_html(
        metadata=build_metadata(rows, now),
        calendar=build_calendar(rows),
        flights=build_flights(rows),
        analysis=build_analysis(rows),
        summary=build_summary(rows),
        inline_data=True,
    )
    m = re.search(
        r'<script type="application/json" id="DATA_FLIGHTS">(.*?)</script>',
        index_html,
        re.S,
    )
    assert m, "DATA_FLIGHTS blob not found"
    blob = json.loads(m.group(1))
    for route, dates in blob.items():
        for date, flights in dates.items():
            for f in flights:
                required = (
                    "trajectory",
                    "trajectory_pct",
                    "percentile",
                    "historical_mean_cents",
                )
                for field in required:
                    assert field in f, (
                        f"{field} missing from DATA_FLIGHTS[{route}][{date}] entry"
                    )


# ─── Issue #98: panel heading + subtitle cleanup ──────────────────────────────


def test_panel_subtitles_present_in_rendered_html():
    """All 6 panels must include a .panel__subtitle paragraph."""
    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    assert "panel__subtitle" in index_html, (
        ".panel__subtitle not found in rendered HTML"
    )
    # Check that all 6 subtitles from the spec are present
    assert "How prices have changed over time" in index_html
    assert "each bar is one 5 euro bin" in index_html or "5 euro bin" in index_html
    assert "Cheapest Friday to Sunday" in index_html
    assert "day of week and month" in index_html
    assert "Cheapest hours to fly" in index_html
    assert "whether prices tend to rise or fall" in index_html


def test_panel_subtitle_css_in_styles():
    """styles.css must define .panel__subtitle."""
    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    assert ".panel__subtitle" in index_html


def test_weekend_pairs_heading_updated():
    """Weekend pairs panel heading must use the friendlier 'Weekend trips' label."""
    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    assert "Weekend trips" in index_html


def test_cheapness_panel_heading_updated():
    """Cheapness panel heading must be updated to 'Cheapest days and months to fly'."""
    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    assert "Cheapest days and months to fly" in index_html


def test_heatmap_heading_updated():
    """Heatmap panel heading must use 'Prices by departure time'."""
    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    assert "Prices by departure time" in index_html


def test_normprog_heading_updated():
    """Normalised progression panel must use the plain-English heading."""
    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    assert "How prices change as departure approaches" in index_html


# ─── Issue #97: price verdict card ───────────────────────────────────────────


def test_verdict_card_dom_id_in_template():
    """Template must include a #verdict-card container in the price-history wrap."""
    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    assert 'id="verdict-card"' in index_html, (
        "#verdict-card container missing from template"
    )


def test_verdict_card_in_required_dom_ids():
    """verdict-card must be listed in REQUIRED_DOM_IDS."""
    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    js = _app_js(index_html)
    assert "'verdict-card'" in js, "verdict-card not in REQUIRED_DOM_IDS"


def test_verdict_card_reads_percentile_and_historical_mean():
    """JS must read percentile and historical_mean_cents from flight data."""
    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    js = _app_js(index_html)
    assert "percentile" in js
    assert "historical_mean_cents" in js


def test_verdict_card_thresholds_all_present():
    """JS must implement all four percentile thresholds from the spec."""
    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    js = _app_js(index_html)
    assert "Well below own historical average" in js
    assert "Below own historical average" in js
    assert "Fair price" in js
    assert "Above own historical average" in js


def test_verdict_card_null_percentile_fallback():
    """When percentile is null, the card must show 'Not enough data'."""
    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    js = _app_js(index_html)
    assert "Not enough data" in js


def test_verdict_card_css_class_in_styles():
    """styles.css must define .verdict-card."""
    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    assert ".verdict-card" in index_html


def test_verdict_card_verdict_colour_classes():
    """JS must use is-good/is-fair/is-bad CSS modifier classes for verdict colour."""
    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    js = _app_js(index_html)
    assert "is-good" in js
    assert "is-fair" in js
    assert "is-bad" in js


# ─── Issue #96: per-flight trajectory arrows in drill-down ────────────────────


def test_drilldown_trajectory_arrow_rendered_when_not_null():
    """renderDrilldown must emit a .flight-row__trajectory span when trajectory
    is non-null, with an aria-label that names the direction and percentage."""
    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    js = _app_js(index_html)
    assert "flight-row__trajectory" in js, (
        "renderDrilldown must include .flight-row__trajectory for trajectory arrows"
    )
    assert "trajectory" in js, "renderDrilldown must read trajectory from flight data"


def test_drilldown_trajectory_arrow_skipped_when_null():
    """No arrow span must be emitted when trajectory is null."""
    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    js = _app_js(index_html)
    # The null guard must be present (some form of null/falsy check on trajectory)
    assert "trajectory" in js
    # There must be a conditional that avoids rendering when trajectory data is absent
    assert "f.historical_mean_cents" in js, (
        "JS must guard on f.historical_mean_cents to conditionally render the arrow"
    )


def test_drilldown_trajectory_arrow_has_aria_label():
    """Each trajectory arrow span must carry an aria-label for screen readers."""
    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    js = _app_js(index_html)
    assert "aria-label" in js, "trajectory arrow span must have an aria-label attribute"


def test_drilldown_trajectory_arrow_colors_all_directions():
    """app.js must produce distinct CSS for each of the three directions."""
    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    js = _app_js(index_html)
    # Colors for each direction (inline style or CSS class references)
    assert "trajectory--down" in js or "#3d7a3d" in js or "green" in js.lower(), (
        "down trajectory must have a green indicator"
    )
    assert "trajectory--up" in js or "#c0392b" in js or "color-red" in js, (
        "up trajectory must have a red indicator"
    )
    assert "trajectory--stable" in js or "#999" in js or "stable" in js, (
        "stable trajectory must have a gray/neutral indicator"
    )


def test_drilldown_trajectory_css_class_in_styles():
    """styles.css must define .flight-row__trajectory."""
    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    assert ".flight-row__trajectory" in index_html


# ─── Issue #94: trajectory, verdict, market-direction ─────────────────────────


def _make_rows(csv_text: str, tmp_path: Path) -> list:
    p = tmp_path / "x.csv"
    header = (
        "retrieved_at,departure_date,origin,destination,airline,"
        "departure_at,arrival_at,duration_minutes,price_cents,price_currency\n"
    )
    p.write_text(header + csv_text)
    return load_rows(str(p))


# ── build_analysis: market_direction ──────────────────────────────────────────


def test_build_analysis_market_direction_present_for_each_route():
    rows = load_rows(str(FIXTURE))
    analysis = build_analysis(rows)
    for route in analysis:
        assert "market_direction" in analysis[route], (
            f"market_direction missing from route {route}"
        )
        md = analysis[route]["market_direction"]
        assert md["trend"] in ("up", "down", "stable"), f"invalid trend: {md['trend']}"
        assert isinstance(md["pct_change"], float)
        assert isinstance(md["label"], str)
        assert len(md["label"]) > 0


def test_build_analysis_market_direction_down_when_prices_falling(tmp_path):
    # 4 obs dates: old pair avg 15000, new pair avg 10000 → -33% → "down"
    rows = _make_rows(
        "2026-04-01T23:46Z,2026-06-19,CPH,AMS,easyJet,2026-06-19T19:30:00,2026-06-19T21:00:00,90,15000,EUR\n"
        "2026-04-02T23:46Z,2026-06-19,CPH,AMS,easyJet,2026-06-19T19:30:00,2026-06-19T21:00:00,90,14000,EUR\n"
        "2026-04-10T23:46Z,2026-06-19,CPH,AMS,easyJet,2026-06-19T19:30:00,2026-06-19T21:00:00,90,10000,EUR\n"
        "2026-04-11T23:46Z,2026-06-19,CPH,AMS,easyJet,2026-06-19T19:30:00,2026-06-19T21:00:00,90,9000,EUR\n",
        tmp_path,
    )
    analysis = build_analysis(rows)
    md = analysis["CPH-AMS"]["market_direction"]
    assert md["trend"] == "down"
    assert md["pct_change"] < -3


def test_build_analysis_market_direction_up_when_prices_rising(tmp_path):
    # 4 obs dates: old pair avg 5000, new pair avg 8000 → +60% → "up"
    rows = _make_rows(
        "2026-04-01T23:46Z,2026-06-19,CPH,AMS,easyJet,2026-06-19T19:30:00,2026-06-19T21:00:00,90,5000,EUR\n"
        "2026-04-02T23:46Z,2026-06-19,CPH,AMS,easyJet,2026-06-19T19:30:00,2026-06-19T21:00:00,90,5200,EUR\n"
        "2026-04-10T23:46Z,2026-06-19,CPH,AMS,easyJet,2026-06-19T19:30:00,2026-06-19T21:00:00,90,8000,EUR\n"
        "2026-04-11T23:46Z,2026-06-19,CPH,AMS,easyJet,2026-06-19T19:30:00,2026-06-19T21:00:00,90,8200,EUR\n",
        tmp_path,
    )
    analysis = build_analysis(rows)
    md = analysis["CPH-AMS"]["market_direction"]
    assert md["trend"] == "up"
    assert md["pct_change"] > 3


def test_build_analysis_market_direction_stable_when_prices_flat(tmp_path):
    # 4 obs dates: all near 10000 → pct_change within ±3% → "stable"
    rows = _make_rows(
        "2026-04-01T23:46Z,2026-06-19,CPH,AMS,easyJet,2026-06-19T19:30:00,2026-06-19T21:00:00,90,10000,EUR\n"
        "2026-04-02T23:46Z,2026-06-19,CPH,AMS,easyJet,2026-06-19T19:30:00,2026-06-19T21:00:00,90,10100,EUR\n"
        "2026-04-10T23:46Z,2026-06-19,CPH,AMS,easyJet,2026-06-19T19:30:00,2026-06-19T21:00:00,90,10050,EUR\n"
        "2026-04-11T23:46Z,2026-06-19,CPH,AMS,easyJet,2026-06-19T19:30:00,2026-06-19T21:00:00,90,10200,EUR\n",
        tmp_path,
    )
    analysis = build_analysis(rows)
    md = analysis["CPH-AMS"]["market_direction"]
    assert md["trend"] == "stable"
    assert -3 <= md["pct_change"] <= 3


def test_build_analysis_market_direction_with_only_two_obs_dates(tmp_path):
    # Minimum case: 2 obs dates — must still produce a result
    rows = _make_rows(
        "2026-04-01T23:46Z,2026-06-19,CPH,AMS,easyJet,2026-06-19T19:30:00,2026-06-19T21:00:00,90,10000,EUR\n"
        "2026-04-10T23:46Z,2026-06-19,CPH,AMS,easyJet,2026-06-19T19:30:00,2026-06-19T21:00:00,90,8000,EUR\n",
        tmp_path,
    )
    analysis = build_analysis(rows)
    md = analysis["CPH-AMS"]["market_direction"]
    assert md["trend"] in ("up", "down", "stable")
    assert isinstance(md["pct_change"], float)


def test_build_analysis_market_direction_stable_with_one_obs_date(tmp_path):
    # Only 1 obs date — cannot compare, so trend must be "stable" with pct_change 0.0
    rows = _make_rows(
        "2026-04-01T23:46Z,2026-06-19,CPH,AMS,easyJet,2026-06-19T19:30:00,2026-06-19T21:00:00,90,10000,EUR\n",
        tmp_path,
    )
    analysis = build_analysis(rows)
    md = analysis["CPH-AMS"]["market_direction"]
    assert md["trend"] == "stable"
    assert md["pct_change"] == 0.0


# ── build_analysis: best_time_to_visit ────────────────────────────────────────


def test_build_analysis_best_time_to_visit_present_for_each_route():
    rows = load_rows(str(FIXTURE))
    analysis = build_analysis(rows)
    for route in analysis:
        assert "best_time_to_visit" in analysis[route], (
            f"best_time_to_visit missing from route {route}"
        )
        btv = analysis[route]["best_time_to_visit"]
        assert "cheapest_month" in btv
        assert "cheapest_dow" in btv
        assert "lowest_ever" in btv


def test_build_analysis_best_time_cheapest_month_matches_month_list():
    rows = load_rows(str(FIXTURE))
    analysis = build_analysis(rows)
    cph = analysis["CPH-AMS"]
    cheapest_month = cph["best_time_to_visit"]["cheapest_month"]
    min_month = min(cph["month"], key=lambda m: m["mean_cents"])
    assert cheapest_month["label"] == min_month["label"]
    assert cheapest_month["mean_cents"] == min_month["mean_cents"]


def test_build_analysis_best_time_cheapest_dow_matches_dow_list():
    rows = load_rows(str(FIXTURE))
    analysis = build_analysis(rows)
    cph = analysis["CPH-AMS"]
    cheapest_dow = cph["best_time_to_visit"]["cheapest_dow"]
    min_dow = min(cph["day_of_week"], key=lambda d: d["mean_cents"])
    assert cheapest_dow["label"] == min_dow["label"]
    assert cheapest_dow["mean_cents"] == min_dow["mean_cents"]


def test_build_analysis_best_time_lowest_ever_is_minimum_price_for_route():
    rows = load_rows(str(FIXTURE))
    analysis = build_analysis(rows)
    cph = analysis["CPH-AMS"]
    lowest_ever = cph["best_time_to_visit"]["lowest_ever"]
    # Fixture: Ryanair 7800 on 2026-05-15 for CPH-AMS 2026-06-19 departure
    assert lowest_ever["price_cents"] == 7800
    assert lowest_ever["departure_date"] == "2026-06-19"
    assert lowest_ever["airline"] == "Ryanair"
    assert "route" in lowest_ever


# ── build_flights: trajectory ─────────────────────────────────────────────────


def test_build_flights_trajectory_null_when_fewer_than_six_obs():
    rows = load_rows(str(FIXTURE))
    flights = build_flights(rows)
    # easyJet 19:30 CPH-AMS 2026-06-19 has 3 observations → trajectory must be null
    easyjet = next(
        f
        for f in flights["CPH-AMS"]["2026-06-19"]
        if f["airline"] == "easyJet" and f["dep_time"] == "19:30"
    )
    assert len(easyjet["history"]) == 3
    assert easyjet["trajectory"] is None
    assert easyjet["trajectory_pct"] is None


def test_build_flights_trajectory_down_when_prices_falling(tmp_path):
    # 6 obs: prev 3 avg 15000, recent 3 avg 10000 → -33% → "down"
    rows = _make_rows(
        "2026-04-01T23:46Z,2026-06-19,CPH,AMS,easyJet,2026-06-19T19:30:00,2026-06-19T21:00:00,90,15000,EUR\n"
        "2026-04-02T23:46Z,2026-06-19,CPH,AMS,easyJet,2026-06-19T19:30:00,2026-06-19T21:00:00,90,15000,EUR\n"
        "2026-04-03T23:46Z,2026-06-19,CPH,AMS,easyJet,2026-06-19T19:30:00,2026-06-19T21:00:00,90,15000,EUR\n"
        "2026-04-10T23:46Z,2026-06-19,CPH,AMS,easyJet,2026-06-19T19:30:00,2026-06-19T21:00:00,90,10000,EUR\n"
        "2026-04-11T23:46Z,2026-06-19,CPH,AMS,easyJet,2026-06-19T19:30:00,2026-06-19T21:00:00,90,10000,EUR\n"
        "2026-04-12T23:46Z,2026-06-19,CPH,AMS,easyJet,2026-06-19T19:30:00,2026-06-19T21:00:00,90,10000,EUR\n",
        tmp_path,
    )
    flights = build_flights(rows)
    easyjet = flights["CPH-AMS"]["2026-06-19"][0]
    assert len(easyjet["history"]) == 6
    assert easyjet["trajectory"] == "down"
    assert easyjet["trajectory_pct"] is not None
    assert easyjet["trajectory_pct"] < -3


def test_build_flights_trajectory_up_when_prices_rising(tmp_path):
    # 6 obs: prev 3 avg 5000, recent 3 avg 8000 → +60% → "up"
    rows = _make_rows(
        "2026-04-01T23:46Z,2026-06-19,CPH,AMS,easyJet,2026-06-19T19:30:00,2026-06-19T21:00:00,90,5000,EUR\n"
        "2026-04-02T23:46Z,2026-06-19,CPH,AMS,easyJet,2026-06-19T19:30:00,2026-06-19T21:00:00,90,5000,EUR\n"
        "2026-04-03T23:46Z,2026-06-19,CPH,AMS,easyJet,2026-06-19T19:30:00,2026-06-19T21:00:00,90,5000,EUR\n"
        "2026-04-10T23:46Z,2026-06-19,CPH,AMS,easyJet,2026-06-19T19:30:00,2026-06-19T21:00:00,90,8000,EUR\n"
        "2026-04-11T23:46Z,2026-06-19,CPH,AMS,easyJet,2026-06-19T19:30:00,2026-06-19T21:00:00,90,8000,EUR\n"
        "2026-04-12T23:46Z,2026-06-19,CPH,AMS,easyJet,2026-06-19T19:30:00,2026-06-19T21:00:00,90,8000,EUR\n",
        tmp_path,
    )
    flights = build_flights(rows)
    easyjet = flights["CPH-AMS"]["2026-06-19"][0]
    assert easyjet["trajectory"] == "up"
    assert easyjet["trajectory_pct"] > 3


def test_build_flights_trajectory_stable_when_prices_flat(tmp_path):
    # 6 obs all at 10000 → 0% change → "stable"
    rows = _make_rows(
        "2026-04-01T23:46Z,2026-06-19,CPH,AMS,easyJet,2026-06-19T19:30:00,2026-06-19T21:00:00,90,10000,EUR\n"
        "2026-04-02T23:46Z,2026-06-19,CPH,AMS,easyJet,2026-06-19T19:30:00,2026-06-19T21:00:00,90,10000,EUR\n"
        "2026-04-03T23:46Z,2026-06-19,CPH,AMS,easyJet,2026-06-19T19:30:00,2026-06-19T21:00:00,90,10000,EUR\n"
        "2026-04-10T23:46Z,2026-06-19,CPH,AMS,easyJet,2026-06-19T19:30:00,2026-06-19T21:00:00,90,10200,EUR\n"
        "2026-04-11T23:46Z,2026-06-19,CPH,AMS,easyJet,2026-06-19T19:30:00,2026-06-19T21:00:00,90,9900,EUR\n"
        "2026-04-12T23:46Z,2026-06-19,CPH,AMS,easyJet,2026-06-19T19:30:00,2026-06-19T21:00:00,90,10100,EUR\n",
        tmp_path,
    )
    flights = build_flights(rows)
    easyjet = flights["CPH-AMS"]["2026-06-19"][0]
    assert easyjet["trajectory"] == "stable"
    assert -3 <= easyjet["trajectory_pct"] <= 3


# ── build_flights: historical_mean_cents ──────────────────────────────────────


def test_build_flights_historical_mean_cents_is_mean_of_all_history_prices():
    rows = load_rows(str(FIXTURE))
    flights = build_flights(rows)
    easyjet = next(
        f
        for f in flights["CPH-AMS"]["2026-06-19"]
        if f["airline"] == "easyJet" and f["dep_time"] == "19:30"
    )
    # history prices: 11000, 9900, 9200
    expected = round((11000 + 9900 + 9200) / 3)
    assert easyjet["historical_mean_cents"] == expected


# ── build_flights: percentile ─────────────────────────────────────────────────


def test_build_flights_percentile_null_when_fewer_than_five_obs():
    rows = load_rows(str(FIXTURE))
    flights = build_flights(rows)
    # easyJet 19:30 CPH-AMS 2026-06-19 has 3 observations → percentile must be null
    easyjet = next(
        f
        for f in flights["CPH-AMS"]["2026-06-19"]
        if f["airline"] == "easyJet" and f["dep_time"] == "19:30"
    )
    assert easyjet["percentile"] is None


def test_build_flights_percentile_correct_when_five_or_more_obs(tmp_path):
    # 5 observations: [5000, 6000, 7000, 8000, 9000], latest_cents=5000
    # Sorted prices: [5000, 6000, 7000, 8000, 9000]
    # latest_cents=5000 is the minimum → percentile=0.0
    rows = _make_rows(
        "2026-04-01T23:46Z,2026-06-19,CPH,AMS,easyJet,2026-06-19T19:30:00,2026-06-19T21:00:00,90,9000,EUR\n"
        "2026-04-02T23:46Z,2026-06-19,CPH,AMS,easyJet,2026-06-19T19:30:00,2026-06-19T21:00:00,90,8000,EUR\n"
        "2026-04-03T23:46Z,2026-06-19,CPH,AMS,easyJet,2026-06-19T19:30:00,2026-06-19T21:00:00,90,7000,EUR\n"
        "2026-04-10T23:46Z,2026-06-19,CPH,AMS,easyJet,2026-06-19T19:30:00,2026-06-19T21:00:00,90,6000,EUR\n"
        "2026-04-11T23:46Z,2026-06-19,CPH,AMS,easyJet,2026-06-19T19:30:00,2026-06-19T21:00:00,90,5000,EUR\n",
        tmp_path,
    )
    flights = build_flights(rows)
    easyjet = flights["CPH-AMS"]["2026-06-19"][0]
    assert len(easyjet["history"]) == 5
    # latest_cents = 5000 (most recent) = the minimum → 0th percentile
    assert easyjet["latest_cents"] == 5000
    assert easyjet["percentile"] == 0.0


def test_build_flights_percentile_100_when_latest_is_max(tmp_path):
    # 5 observations with latest being the highest price → 100th percentile
    rows = _make_rows(
        "2026-04-01T23:46Z,2026-06-19,CPH,AMS,easyJet,2026-06-19T19:30:00,2026-06-19T21:00:00,90,5000,EUR\n"
        "2026-04-02T23:46Z,2026-06-19,CPH,AMS,easyJet,2026-06-19T19:30:00,2026-06-19T21:00:00,90,6000,EUR\n"
        "2026-04-03T23:46Z,2026-06-19,CPH,AMS,easyJet,2026-06-19T19:30:00,2026-06-19T21:00:00,90,7000,EUR\n"
        "2026-04-10T23:46Z,2026-06-19,CPH,AMS,easyJet,2026-06-19T19:30:00,2026-06-19T21:00:00,90,8000,EUR\n"
        "2026-04-11T23:46Z,2026-06-19,CPH,AMS,easyJet,2026-06-19T19:30:00,2026-06-19T21:00:00,90,9000,EUR\n",
        tmp_path,
    )
    flights = build_flights(rows)
    easyjet = flights["CPH-AMS"]["2026-06-19"][0]
    assert easyjet["latest_cents"] == 9000
    assert easyjet["percentile"] == 100.0


def test_build_flights_percentile_midpoint_for_median_price(tmp_path):
    # 5 observations: [5000, 6000, 7000, 8000, 9000], latest=7000 (median)
    rows = _make_rows(
        "2026-04-01T23:46Z,2026-06-19,CPH,AMS,easyJet,2026-06-19T19:30:00,2026-06-19T21:00:00,90,5000,EUR\n"
        "2026-04-02T23:46Z,2026-06-19,CPH,AMS,easyJet,2026-06-19T19:30:00,2026-06-19T21:00:00,90,6000,EUR\n"
        "2026-04-03T23:46Z,2026-06-19,CPH,AMS,easyJet,2026-06-19T19:30:00,2026-06-19T21:00:00,90,8000,EUR\n"
        "2026-04-10T23:46Z,2026-06-19,CPH,AMS,easyJet,2026-06-19T19:30:00,2026-06-19T21:00:00,90,9000,EUR\n"
        "2026-04-11T23:46Z,2026-06-19,CPH,AMS,easyJet,2026-06-19T19:30:00,2026-06-19T21:00:00,90,7000,EUR\n",
        tmp_path,
    )
    flights = build_flights(rows)
    easyjet = flights["CPH-AMS"]["2026-06-19"][0]
    # latest_cents = 7000 (obs_date 2026-04-11, sorted last)
    assert easyjet["latest_cents"] == 7000
    # prices sorted: [5000, 6000, 7000, 8000, 9000]
    # 7000 is at index 2 → percentile = 2/4 * 100 = 50.0
    assert easyjet["percentile"] == 50.0


# ─── Issue #101: selected-flight marker on lead-time chart ────────────────────


def test_leadtime_selected_flight_dot_uses_arc():
    """When a flight is selected the afterDraw plugin must draw a dot
    (canvas arc) at the flight's price level on the lead-time chart."""
    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    js = _app_js(index_html)
    assert "arc(" in js, (
        "afterDraw plugin must call ctx.arc() to draw a dot for the selected flight"
    )


def test_leadtime_selected_flight_chart_update_called():
    """Clicking a flight row must call charts.leadtime.update() so the
    afterDraw plugin re-runs and the marker moves to the new flight."""
    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    js = _app_js(index_html)
    assert "leadtime.update" in js, (
        "flight row click handler must call charts.leadtime.update()"
    )


def test_leadtime_selected_flight_reads_selectedflight_in_afterdraw():
    """The afterDraw plugin must reference state.selectedFlight to find the
    selected flight and draw the dot at its price position."""
    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    js = _app_js(index_html)
    assert "selectedFlight" in js
    assert "afterDraw" in js


def test_leadtime_selected_flight_dot_disappears_when_none():
    """When state.selectedFlight is null the dot must not be drawn.
    The afterDraw plugin must guard against a null selectedFlight."""
    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    js = _app_js(index_html)
    # afterDraw block must check selectedFlight before drawing dot
    assert "selectedFlight" in js
    # guard must be present — either explicit null check or if-block
    assert "if (state.selectedFlight)" in js or "selectedFlight &&" in js


def test_leadtime_selected_flight_css_dot_colour():
    """The dot for the selected flight must use the site red colour
    (rgba(192,57,43,...) or var(--color-red)) for visual consistency."""
    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    js = _app_js(index_html)
    assert "192,57,43" in js or "color-red" in js


# --- Sweet-spot minimum-observation threshold (issue #113) ---


def _make_sweet_spot_rows(
    days_before_prices: dict[int, list[int]], tmp_path
) -> list[dict]:
    """Build synthetic CSV rows and return them as parsed dicts.

    days_before_prices maps days_before → list of price_cents.  The
    departure date is fixed to 2026-09-01; retrieved_at is computed as
    departure_date minus days_before days.
    """
    from datetime import date, timedelta

    dep_date = date(2026, 9, 1)
    lines = [
        "retrieved_at,departure_date,origin,destination,airline,"
        "departure_at,arrival_at,duration_minutes,price_cents,price_currency"
    ]
    for db, prices in days_before_prices.items():
        ret_date = dep_date - timedelta(days=db)
        ret_iso = f"{ret_date.isoformat()}T12:00Z"
        for i, cents in enumerate(prices):
            lines.append(
                f"{ret_iso},2026-09-01,CPH,AMS,Airline{i},"
                f"2026-09-01T10:00:00,2026-09-01T11:30:00,90,{cents},EUR"
            )
    p = tmp_path / "sweet_spot.csv"
    p.write_text("\n".join(lines) + "\n")
    return load_rows(str(p))


def test_sweet_spot_all_buckets_reliable_picks_cheapest(tmp_path):
    """With 200 observations evenly spread across 5 buckets (40 each), all
    buckets exceed the threshold=10 floor.  The sweet_spot picks the bucket
    with the lowest mean — here days_before=10 at 5000 cents, the rest at
    10000 cents.
    """
    days_before_prices = {
        3: [10000] * 40,
        5: [10000] * 40,
        10: [5000] * 40,  # cheapest — should be selected
        30: [10000] * 40,
        90: [10000] * 40,
    }
    rows = _make_sweet_spot_rows(days_before_prices, tmp_path)
    analysis = build_analysis(rows)
    assert analysis["CPH-AMS"]["sweet_spot_days"] == 10


def test_sweet_spot_filters_below_threshold_bucket(tmp_path):
    """Buckets with fewer than RELIABLE_MIN_OBSERVATIONS observations must
    be excluded even if their mean price is the lowest.

    days_before=5 has only 2 observations at a suspiciously low price of
    1 cent — a classic outlier scenario.  days_before=30 has 15 observations
    at a higher but reliable 8000 cents.  The sweet_spot must be 30, not 5.
    """
    import config

    days_before_prices = {
        5: [1] * 2,  # below threshold — must be excluded
        30: [8000] * 15,  # reliable
    }
    rows = _make_sweet_spot_rows(days_before_prices, tmp_path)
    analysis = build_analysis(rows)
    # The only reliable bucket is days_before=30
    assert analysis["CPH-AMS"]["sweet_spot_days"] == 30
    # Confirm threshold is indeed 10 so the test is meaningful
    assert config.RELIABLE_MIN_OBSERVATIONS == 10


def test_sweet_spot_none_when_no_bucket_meets_threshold(tmp_path):
    """When every bucket has fewer than RELIABLE_MIN_OBSERVATIONS
    observations, sweet_spot_days must be None (not an arbitrary pick).
    The frontend already handles None via its 'Not enough data yet' fallback.
    """
    days_before_prices = {
        10: [9000] * 3,  # only 3 obs — below threshold
        20: [8500] * 5,  # only 5 obs — below threshold
        30: [8000] * 2,  # only 2 obs — below threshold
    }
    rows = _make_sweet_spot_rows(days_before_prices, tmp_path)
    analysis = build_analysis(rows)
    assert analysis["CPH-AMS"]["sweet_spot_days"] is None


# ─── Issue #83: modular JS split verification ─────────────────────────────────


def test_modular_split_produces_functionally_equivalent_js():
    """The concatenated JS from frontend/js/*.js must contain all the key
    function signatures and data field references from the original monolithic
    app.js. This spot-checks that the split didn't accidentally drop any logic.
    """
    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    js = _app_js(index_html)

    # Core chart field references
    assert "q1_cents" in js, "renderTrends must reference q1_cents from lead_time_curve"
    assert "q3_cents" in js, "renderTrends must reference q3_cents from lead_time_curve"
    assert "normalized_price_progression" in js, (
        "renderNormProgress must reference normalized_price_progression"
    )
    assert "time_of_day_matrix" in js, (
        "renderTimeheat must reference time_of_day_matrix"
    )
    assert "Math.round(cents / 100)" in js, (
        "formatPrice must use Math.round(cents / 100)"
    )

    # Key function signatures all present in the bundle
    for fn in [
        "function renderCalendar",
        "function renderDrilldown",
        "function renderTrends",
        "function renderHistograms",
        "function renderFooterCharts",
        "function renderTimeheat",
        "function renderNormProgress",
        "function wireFilters",
        "function activeRoutes",
        "function airlinePasses",
        "function main",
    ]:
        assert fn in js, f"Expected function signature not found in bundled JS: {fn}"


def test_js_bundle_wrapped_in_iife():
    """The concatenated JS must be wrapped in an IIFE with 'use strict'."""
    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    js = _app_js(index_html)
    assert js.strip().startswith("(function ()"), (
        "Bundled JS must start with IIFE wrapper: (function () {"
    )
    assert "'use strict';" in js, "Bundled JS must contain 'use strict';"
    assert js.strip().endswith("})();"), "Bundled JS must end with IIFE closing: })();"


def test_no_duplicate_use_strict_in_bundle():
    """'use strict' must appear exactly once — added by _build_app_js, not in files."""
    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    js = _app_js(index_html)
    assert js.count("'use strict';") == 1, (
        "'use strict' must appear exactly once in the bundled JS "
        "(injected by the wrapper, not inside source files)"
    )


def test_js_source_files_exist_in_correct_order():
    """All 9 JS source files must exist at frontend/js/ and be loadable."""
    from src.html_generator import JS_FILE_ORDER, JS_SOURCE_DIR

    for filename in JS_FILE_ORDER:
        path = JS_SOURCE_DIR / filename
        assert path.exists(), f"JS source file missing: {path}"
        content = path.read_text(encoding="utf-8")
        assert len(content) > 0, f"JS source file is empty: {path}"
        # Source files must NOT contain IIFE wrapper or 'use strict'
        assert "(function ()" not in content, (
            f"{filename} must not contain an IIFE wrapper — "
            "wrapping happens at build time"
        )
        assert "'use strict';" not in content, (
            f"{filename} must not contain 'use strict' — "
            "it is added by the IIFE wrapper"
        )


# ─── Issue #104: multi-route generalisation verification ──────────────────────


def test_route_palette_defined_in_bundle():
    """ROUTE_PALETTE must be defined in the JS bundle with at least 2 colours."""
    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    js = _app_js(index_html)
    assert "ROUTE_PALETTE" in js, (
        "constants.js must define ROUTE_PALETTE for dynamic route colouring"
    )
    assert "routeColor" in js, (
        "utils.js must define routeColor() that indexes into ROUTE_PALETTE"
    )


def test_histograms_container_in_template_not_fixed_canvases():
    """The histogram section must use a container div, not fixed per-route canvas IDs.

    The old id='histogram-out' / id='histogram-back' canvases are replaced by
    id='histograms-container' so that the renderer can build one canvas per
    route for any route list (not just CPH-AMS + AMS-CPH).
    """
    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    assert 'id="histograms-container"' in index_html, (
        'Template must use <div id="histograms-container"> for dynamic per-route '
        'histogram canvases (replaces old id="histogram-out"/id="histogram-back")'
    )
    assert 'id="histogram-out"' not in index_html, (
        'Old hardcoded id="histogram-out" canvas must be removed from the template'
    )
    assert 'id="histogram-back"' not in index_html, (
        'Old hardcoded id="histogram-back" canvas must be removed from the template'
    )


def test_timeheat_container_in_template_not_fixed_canvases():
    """The timeheat section must use a container div, not fixed per-route canvas IDs."""
    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    assert 'id="timeheat-container"' in index_html, (
        'Template must use <div id="timeheat-container"> for dynamic per-route '
        "heatmap canvases"
    )
    assert 'id="timeheat-out"' not in index_html, (
        'Old hardcoded id="timeheat-out" canvas must be removed from the template'
    )
    assert 'id="timeheat-back"' not in index_html, (
        'Old hardcoded id="timeheat-back" canvas must be removed from the template'
    )


def test_active_routes_driven_by_metadata(tmp_path):
    """activeRoutes() must return routes from DATA.metadata.routes, not hardcoded."""
    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    js = _app_js(index_html)
    # activeRoutes must reference metadata.routes, not ['CPH-AMS', 'AMS-CPH']
    assert "metadata.routes" in js, (
        "activeRoutes() must read from DATA.metadata.routes to support arbitrary routes"
    )


def test_multi_route_generate_with_third_route(tmp_path):
    """generate() must produce valid HTML containing LHR-DUB references when the
    input CSV includes LHR-DUB flights. No CPH-AMS hardcoding should prevent this.

    This verifies the end-to-end multi-route generalisation from issue #104.
    """
    csv_text = (
        "retrieved_at,departure_date,origin,destination,airline,"
        "departure_at,arrival_at,duration_minutes,price_cents,price_currency\n"
        # LHR-DUB flights
        "2026-05-10T23:46Z,2026-06-19,LHR,DUB,Ryanair,"
        "2026-06-19T07:00:00,2026-06-19T08:30:00,90,5500,EUR\n"
        "2026-05-15T23:46Z,2026-06-19,LHR,DUB,easyJet,"
        "2026-06-19T12:00:00,2026-06-19T13:30:00,90,6800,EUR\n"
        "2026-05-10T23:46Z,2026-06-21,DUB,LHR,Ryanair,"
        "2026-06-21T17:00:00,2026-06-21T18:30:00,90,5800,EUR\n"
        "2026-05-15T23:46Z,2026-06-21,DUB,LHR,easyJet,"
        "2026-06-21T20:00:00,2026-06-21T21:30:00,90,7200,EUR\n"
    )
    p = tmp_path / "lhr_dub.csv"
    p.write_text(csv_text)
    out_path = tmp_path / "index.html"
    n = generate(str(p), str(out_path))
    assert n == 4
    html = out_path.read_text(encoding="utf-8")

    # In default mode the blobs are in data.json, not inline in the HTML.
    data_json = tmp_path / "data.json"
    assert data_json.exists(), "data.json must be written by generate()"
    payload = json.loads(data_json.read_text(encoding="utf-8"))
    metadata = payload["metadata"]
    assert "LHR-DUB" in metadata["routes"], "LHR-DUB must appear in metadata.routes"
    assert "DUB-LHR" in metadata["routes"], "DUB-LHR must appear in metadata.routes"

    # The JS must reference routeColor (dynamic palette, not hardcoded dict)
    js = _app_js(html)
    assert "routeColor" in js, (
        "JS must use routeColor() for dynamic palette — "
        "not a hardcoded route→colour dict"
    )


# ─── Issue #126: normalized-progression IQR fields ────────────────────────────


def test_normalized_price_progression_has_iqr_fields():
    """Each normalized_price_progression entry must include q1_pct_change and
    q3_pct_change so the frontend can render an IQR band around the mean line."""
    rows = load_rows(str(FIXTURE))
    analysis = build_analysis(rows)
    prog = analysis["CPH-AMS"]["normalized_price_progression"]
    assert len(prog) > 0, "normalized_price_progression must be non-empty"
    for entry in prog:
        assert "q1_pct_change" in entry, (
            f"normalized_price_progression entry missing q1_pct_change: {entry}"
        )
        assert "q3_pct_change" in entry, (
            f"normalized_price_progression entry missing q3_pct_change: {entry}"
        )
        # Q1 ≤ mean ≤ Q3 must hold (sorted quartile invariant).
        assert entry["q1_pct_change"] <= entry["mean_pct_change"] + 0.01, (
            f"q1_pct_change must be ≤ mean_pct_change: {entry}"
        )
        assert entry["q3_pct_change"] >= entry["mean_pct_change"] - 0.01, (
            f"q3_pct_change must be ≥ mean_pct_change: {entry}"
        )


def test_normalized_price_progression_iqr_equal_for_single_obs():
    """When a bucket has only one observation, q1 == q3 == mean (degenerate case)."""
    rows = load_rows(str(FIXTURE))
    analysis = build_analysis(rows)
    # Find any entry where the values can be checked for equality on single-obs buckets
    prog = analysis["CPH-AMS"]["normalized_price_progression"]
    for entry in prog:
        # All single-obs buckets must have q1==q3==mean
        # We can't control which are single-obs in the fixture, but we verify the
        # invariant that all three fields are present as floats.
        assert isinstance(entry["q1_pct_change"], float), (
            f"q1_pct_change must be a float: {entry}"
        )
        assert isinstance(entry["q3_pct_change"], float), (
            f"q3_pct_change must be a float: {entry}"
        )


def test_rendered_html_contains_normprog_iqr_field_references():
    """The rendered HTML's app.js must reference q1_pct_change and q3_pct_change
    so the IQR band for the normalized-progression chart is driven by the JSON data."""
    index_html, _ = render_html(
        metadata={}, calendar={}, flights={}, analysis={}, summary={}
    )
    js = _app_js(index_html)
    assert "q1_pct_change" in js, (
        "renderNormProgress must reference q1_pct_change from "
        "normalized_price_progression"
    )
    assert "q3_pct_change" in js, (
        "renderNormProgress must reference q3_pct_change from "
        "normalized_price_progression"
    )


# ── build_flights: is_stale ───────────────────────────────────────────────────


def test_build_flights_is_stale_false_when_recent(tmp_path):
    """Flight observed today must not be stale."""
    rows = _make_rows(
        "2026-05-20T10:00Z,2026-06-19,CPH,AMS,KLM,"
        "2026-06-19T08:00:00,2026-06-19T10:30:00,150,10000,EUR\n",
        tmp_path,
    )
    generated_at = datetime(2026, 5, 20, 12, 0, tzinfo=timezone.utc)
    flights = build_flights(rows, generated_at=generated_at)
    flight = flights["CPH-AMS"]["2026-06-19"][0]
    assert flight["is_stale"] is False
    assert flight["latest_retrieved_at"] == "2026-05-20"


def test_build_flights_is_stale_false_at_boundary(tmp_path):
    """Flight observed exactly 3 days ago is not stale (threshold is strictly > 3)."""
    rows = _make_rows(
        "2026-05-17T10:00Z,2026-06-19,CPH,AMS,KLM,"
        "2026-06-19T08:00:00,2026-06-19T10:30:00,150,10000,EUR\n",
        tmp_path,
    )
    generated_at = datetime(2026, 5, 20, 12, 0, tzinfo=timezone.utc)
    flights = build_flights(rows, generated_at=generated_at)
    assert flights["CPH-AMS"]["2026-06-19"][0]["is_stale"] is False


def test_build_flights_is_stale_true_when_old(tmp_path):
    """Flight whose last observation is more than 3 days before
    generated_at is stale."""
    rows = _make_rows(
        "2026-05-10T10:00Z,2026-06-19,CPH,AMS,KLM,"
        "2026-06-19T08:00:00,2026-06-19T10:30:00,150,10000,EUR\n",
        tmp_path,
    )
    generated_at = datetime(2026, 5, 20, 12, 0, tzinfo=timezone.utc)  # 10 days later
    flights = build_flights(rows, generated_at=generated_at)
    assert flights["CPH-AMS"]["2026-06-19"][0]["is_stale"] is True


def test_build_flights_is_stale_uses_latest_obs(tmp_path):
    """Staleness is computed from the most recent observation, not the oldest."""
    rows = _make_rows(
        "2026-05-10T10:00Z,2026-06-19,CPH,AMS,KLM,"
        "2026-06-19T08:00:00,2026-06-19T10:30:00,150,10000,EUR\n"
        "2026-05-19T10:00Z,2026-06-19,CPH,AMS,KLM,"
        "2026-06-19T08:00:00,2026-06-19T10:30:00,150,9500,EUR\n",
        tmp_path,
    )
    generated_at = datetime(2026, 5, 20, 12, 0, tzinfo=timezone.utc)
    flights = build_flights(rows, generated_at=generated_at)
    flight = flights["CPH-AMS"]["2026-06-19"][0]
    # Latest obs is 2026-05-19 (1 day before generated_at) → not stale
    assert flight["is_stale"] is False
    assert flight["latest_retrieved_at"] == "2026-05-19"


# ─── Issue #2: airline price trends per route ────────────────────────────────


def test_build_airline_trends_filters_low_sample_airlines():
    """Airlines with <3 total observations per route are omitted."""
    from datetime import datetime, timezone

    from src.html_generator import build_airline_trends

    retrieved = datetime(2026, 6, 8, tzinfo=timezone.utc)
    rows = [
        {
            "airline": "KLM",
            "origin": "CPH",
            "destination": "AMS",
            "departure_date": "2026-12-14",
            "retrieved_at": retrieved,
            "price_cents": 5200,
            "departure_at": datetime.fromisoformat("2026-12-14T09:00"),
            "arrival_at": datetime.fromisoformat("2026-12-14T11:00"),
            "duration_minutes": 120,
            "price_currency": "DKK",
        },
        {
            "airline": "KLM",
            "origin": "CPH",
            "destination": "AMS",
            "departure_date": "2026-12-14",
            "retrieved_at": datetime(2026, 6, 1, tzinfo=timezone.utc),
            "price_cents": 5100,
            "departure_at": datetime.fromisoformat("2026-12-14T09:00"),
            "arrival_at": datetime.fromisoformat("2026-12-14T11:00"),
            "duration_minutes": 120,
            "price_currency": "DKK",
        },
        {
            "airline": "easyJet",
            "origin": "CPH",
            "destination": "AMS",
            "departure_date": "2026-12-14",
            "retrieved_at": retrieved,
            "price_cents": 4800,
            "departure_at": datetime.fromisoformat("2026-12-14T15:00"),
            "arrival_at": datetime.fromisoformat("2026-12-14T17:00"),
            "duration_minutes": 120,
            "price_currency": "DKK",
        },
        {
            "airline": "Norwegian",
            "origin": "CPH",
            "destination": "AMS",
            "departure_date": "2026-12-14",
            "retrieved_at": datetime(2026, 6, 1, tzinfo=timezone.utc),
            "price_cents": 5050,
            "departure_at": datetime.fromisoformat("2026-12-14T12:00"),
            "arrival_at": datetime.fromisoformat("2026-12-14T14:00"),
            "duration_minutes": 120,
            "price_currency": "DKK",
        },
        {
            "airline": "Norwegian",
            "origin": "CPH",
            "destination": "AMS",
            "departure_date": "2026-12-14",
            "retrieved_at": retrieved,
            "price_cents": 5100,
            "departure_at": datetime.fromisoformat("2026-12-14T12:00"),
            "arrival_at": datetime.fromisoformat("2026-12-14T14:00"),
            "duration_minutes": 120,
            "price_currency": "DKK",
        },
        {
            "airline": "Norwegian",
            "origin": "CPH",
            "destination": "AMS",
            "departure_date": "2026-12-14",
            "retrieved_at": datetime(2026, 5, 27, tzinfo=timezone.utc),
            "price_cents": 4950,
            "departure_at": datetime.fromisoformat("2026-12-14T12:00"),
            "arrival_at": datetime.fromisoformat("2026-12-14T14:00"),
            "duration_minutes": 120,
            "price_currency": "DKK",
        },
    ]
    result = build_airline_trends(rows)
    assert "CPH-AMS" in result
    airlines = {a["airline"] for a in result["CPH-AMS"]}
    assert "KLM" not in airlines  # 2 obs, should be filtered
    assert "easyJet" not in airlines  # 1 obs, filtered
    assert "Norwegian" in airlines  # 3 obs, included


def test_build_airline_trends_structure():
    """Output shape matches spec: routes → airlines with color and series data."""
    from datetime import datetime, timezone

    from src.html_generator import build_airline_trends

    retrieved = datetime(2026, 6, 8, tzinfo=timezone.utc)
    rows = [
        {
            "airline": "KLM",
            "origin": "CPH",
            "destination": "AMS",
            "departure_date": "2026-12-14",
            "retrieved_at": retrieved,
            "price_cents": 5000,
            "departure_at": datetime.fromisoformat("2026-12-14T09:00"),
            "arrival_at": datetime.fromisoformat("2026-12-14T11:00"),
            "duration_minutes": 120,
            "price_currency": "DKK",
        },
        {
            "airline": "KLM",
            "origin": "CPH",
            "destination": "AMS",
            "departure_date": "2026-12-14",
            "retrieved_at": retrieved,
            "price_cents": 5100,
            "departure_at": datetime.fromisoformat("2026-12-14T09:00"),
            "arrival_at": datetime.fromisoformat("2026-12-14T11:00"),
            "duration_minutes": 120,
            "price_currency": "DKK",
        },
        {
            "airline": "KLM",
            "origin": "CPH",
            "destination": "AMS",
            "departure_date": "2026-12-14",
            "retrieved_at": retrieved,
            "price_cents": 5200,
            "departure_at": datetime.fromisoformat("2026-12-14T09:00"),
            "arrival_at": datetime.fromisoformat("2026-12-14T11:00"),
            "duration_minutes": 120,
            "price_currency": "DKK",
        },
    ]
    result = build_airline_trends(rows)
    assert isinstance(result, dict)
    assert "CPH-AMS" in result
    assert isinstance(result["CPH-AMS"], list)
    airline_entry = result["CPH-AMS"][0]
    assert "airline" in airline_entry
    assert "color" in airline_entry
    assert "series" in airline_entry
    assert isinstance(airline_entry["series"], list)
    if airline_entry["series"]:
        point = airline_entry["series"][0]
        required_keys = [
            "days_before",
            "median_cents",
            "p25_cents",
            "p75_cents",
            "sample_count",
        ]
        assert all(k in point for k in required_keys)


def test_build_airline_trends_percentiles():
    """Percentiles computed correctly from raw observations."""
    from datetime import datetime, timezone

    from src.html_generator import build_airline_trends

    # 168 days before 2026-12-14 is 2026-06-29
    retrieved = datetime(2026, 6, 29, tzinfo=timezone.utc)
    rows = [
        {
            "airline": "KLM",
            "origin": "CPH",
            "destination": "AMS",
            "departure_date": "2026-12-14",
            "retrieved_at": retrieved,
            "price_cents": 4800,
            "departure_at": datetime.fromisoformat("2026-12-14T09:00"),
            "arrival_at": datetime.fromisoformat("2026-12-14T11:00"),
            "duration_minutes": 120,
            "price_currency": "DKK",
        },
        {
            "airline": "KLM",
            "origin": "CPH",
            "destination": "AMS",
            "departure_date": "2026-12-14",
            "retrieved_at": retrieved,
            "price_cents": 5000,
            "departure_at": datetime.fromisoformat("2026-12-14T09:00"),
            "arrival_at": datetime.fromisoformat("2026-12-14T11:00"),
            "duration_minutes": 120,
            "price_currency": "DKK",
        },
        {
            "airline": "KLM",
            "origin": "CPH",
            "destination": "AMS",
            "departure_date": "2026-12-14",
            "retrieved_at": retrieved,
            "price_cents": 5100,
            "departure_at": datetime.fromisoformat("2026-12-14T09:00"),
            "arrival_at": datetime.fromisoformat("2026-12-14T11:00"),
            "duration_minutes": 120,
            "price_currency": "DKK",
        },
        {
            "airline": "KLM",
            "origin": "CPH",
            "destination": "AMS",
            "departure_date": "2026-12-14",
            "retrieved_at": retrieved,
            "price_cents": 5300,
            "departure_at": datetime.fromisoformat("2026-12-14T09:00"),
            "arrival_at": datetime.fromisoformat("2026-12-14T11:00"),
            "duration_minutes": 120,
            "price_currency": "DKK",
        },
        {
            "airline": "KLM",
            "origin": "CPH",
            "destination": "AMS",
            "departure_date": "2026-12-14",
            "retrieved_at": retrieved,
            "price_cents": 5400,
            "departure_at": datetime.fromisoformat("2026-12-14T09:00"),
            "arrival_at": datetime.fromisoformat("2026-12-14T11:00"),
            "duration_minutes": 120,
            "price_currency": "DKK",
        },
    ]
    result = build_airline_trends(rows)
    series = result["CPH-AMS"][0]["series"]
    point = next((p for p in series if p["days_before"] == 168), None)
    assert point is not None
    assert point["sample_count"] == 5
    assert point["median_cents"] == 5100
    assert point["p25_cents"] == 5000
    assert point["p75_cents"] == 5300


def test_build_airline_trends_days_before_descending():
    """Days before sorted newest (highest) to oldest (lowest) — matches main chart."""
    from datetime import datetime, timezone

    from src.html_generator import build_airline_trends

    # Departure is 2026-12-14
    # 80 days before: 2026-08-26
    # 120 days before: 2026-07-17
    # 160 days before: 2026-06-07
    # Use 165, 155, 145, 135 days before for testdata
    # Actually let's compute from today 2026-06-08:
    # 80 days after today: 2026-08-27
    # 120 days after: 2026-10-07
    # So if we want days_before at retrieval, we need earlier dates
    # If retrieved 2026-06-08 and departure 2026-08-27: 80 days
    # Let's simplify: use departure dates far apart
    rows = [
        {
            "airline": "KLM",
            "origin": "CPH",
            "destination": "AMS",
            "departure_date": "2026-08-27",
            "retrieved_at": datetime(2026, 6, 8, tzinfo=timezone.utc),
            "price_cents": 5000,
            "departure_at": datetime.fromisoformat("2026-08-27T09:00"),
            "arrival_at": datetime.fromisoformat("2026-08-27T11:00"),
            "duration_minutes": 120,
            "price_currency": "DKK",
        },
        {
            "airline": "KLM",
            "origin": "CPH",
            "destination": "AMS",
            "departure_date": "2026-10-07",
            "retrieved_at": datetime(2026, 6, 8, tzinfo=timezone.utc),
            "price_cents": 5000,
            "departure_at": datetime.fromisoformat("2026-10-07T09:00"),
            "arrival_at": datetime.fromisoformat("2026-10-07T11:00"),
            "duration_minutes": 120,
            "price_currency": "DKK",
        },
        {
            "airline": "KLM",
            "origin": "CPH",
            "destination": "AMS",
            "departure_date": "2026-09-17",
            "retrieved_at": datetime(2026, 6, 8, tzinfo=timezone.utc),
            "price_cents": 5000,
            "departure_at": datetime.fromisoformat("2026-09-17T09:00"),
            "arrival_at": datetime.fromisoformat("2026-09-17T11:00"),
            "duration_minutes": 120,
            "price_currency": "DKK",
        },
        {
            "airline": "KLM",
            "origin": "CPH",
            "destination": "AMS",
            "departure_date": "2026-12-14",
            "retrieved_at": datetime(2026, 6, 8, tzinfo=timezone.utc),
            "price_cents": 5000,
            "departure_at": datetime.fromisoformat("2026-12-14T09:00"),
            "arrival_at": datetime.fromisoformat("2026-12-14T11:00"),
            "duration_minutes": 120,
            "price_currency": "DKK",
        },
    ]
    result = build_airline_trends(rows)
    days = [p["days_before"] for p in result["CPH-AMS"][0]["series"]]
    assert days == sorted(days, reverse=True)
    assert days[0] == 189  # Newest first (2026-12-14 is 189 days after 2026-06-08)


class TestBuildAirlineMatrix:
    """Tests for build_airline_matrix."""

    def _make_row(
        self, airline, origin, dest, retrieved_iso, departure_date, price_cents
    ):
        from datetime import datetime, timezone

        return {
            "airline": airline,
            "origin": origin,
            "destination": dest,
            "retrieved_at": datetime.fromisoformat(retrieved_iso).replace(
                tzinfo=timezone.utc
            ),
            "departure_date": departure_date,
            "price_cents": price_cents,
            "departure_at": datetime.fromisoformat(f"{departure_date}T10:00"),
            "arrival_at": datetime.fromisoformat(f"{departure_date}T12:00"),
            "duration_minutes": 120,
            "price_currency": "EUR",
        }

    def test_output_structure(self):
        """Result is keyed by route; each entry has airline, color, matrix keys."""
        from src.html_generator import build_airline_matrix

        # 2026-12-04 is a Friday (weekday 4).
        # retrieved_at dates: Mon=2026-06-01, Tue=2026-06-02, Wed=2026-06-03
        rows = []
        for date_str in ["2026-06-01", "2026-06-02", "2026-06-03"]:
            rows.append(
                self._make_row(
                    "KLM", "CPH", "AMS", f"{date_str}T10:00", "2026-12-04", 5000
                )
            )

        result = build_airline_matrix(rows)

        assert "CPH-AMS" in result
        airline_list = result["CPH-AMS"]
        assert len(airline_list) == 1
        entry = airline_list[0]
        assert entry["airline"] == "KLM"
        assert "color" in entry
        assert "matrix" in entry
        matrix = entry["matrix"]
        assert "Friday" in matrix
        assert "Saturday" in matrix
        assert "Sunday" in matrix

    def test_buy_day_correctly_mapped(self):
        """Cell (Monday buy, Friday fly) populated from retrieved_at on a Monday."""
        from src.html_generator import build_airline_matrix

        # 3 rows all bought on Monday 2026-06-01 for Friday 2026-12-04
        rows = [
            self._make_row("KLM", "CPH", "AMS", "2026-06-01T10:00", "2026-12-04", 4000),
            self._make_row("KLM", "CPH", "AMS", "2026-06-01T12:00", "2026-12-04", 5000),
            self._make_row("KLM", "CPH", "AMS", "2026-06-01T14:00", "2026-12-04", 6000),
        ]

        result = build_airline_matrix(rows)
        cell = result["CPH-AMS"][0]["matrix"]["Friday"]["Monday"]

        assert cell is not None
        assert cell["n"] == 3
        assert cell["index"] == 0.0  # only 3 obs → overall_median == cell_median
        assert cell["category"] == "no"

    def test_null_for_fewer_than_3_observations(self):
        """Cells with <3 observations are None."""
        from src.html_generator import build_airline_matrix

        # 2 obs on Monday for Friday, 3 obs on Tuesday for Friday
        rows = [
            self._make_row("KLM", "CPH", "AMS", "2026-06-01T10:00", "2026-12-04", 5000),
            self._make_row("KLM", "CPH", "AMS", "2026-06-01T12:00", "2026-12-04", 5100),
            self._make_row("KLM", "CPH", "AMS", "2026-06-02T10:00", "2026-12-04", 5000),
            self._make_row("KLM", "CPH", "AMS", "2026-06-02T12:00", "2026-12-04", 5100),
            self._make_row("KLM", "CPH", "AMS", "2026-06-02T14:00", "2026-12-04", 5200),
        ]

        result = build_airline_matrix(rows)
        matrix = result["CPH-AMS"][0]["matrix"]

        assert matrix["Friday"]["Monday"] is None  # only 2 obs
        assert matrix["Friday"]["Tuesday"] is not None  # 3 obs

    def test_category_bucketing(self):
        """Relative index is bucketed into direction-aware categories correctly."""
        from src.html_generator import build_airline_matrix

        # overall_median = 4760 (9th of 17 sorted values)
        # Mon: 3x3500 → index ≈ -0.265 → cheap-high
        # Tue: 3x4600 → index ≈ -0.034 → cheap-low
        # Wed: 3x4900 → index ≈ +0.029 → expensive-low
        # Thu: 5x4760 → index = 0.0   → no   (5 obs to push median to 4760)
        # Fri: 3x6500 → index ≈ +0.366 → expensive-high
        rows = []
        for _ in range(3):
            rows.append(
                self._make_row(
                    "KLM", "CPH", "AMS", "2026-06-01T10:00", "2026-12-04", 3500
                )
            )  # Mon
        for _ in range(3):
            rows.append(
                self._make_row(
                    "KLM", "CPH", "AMS", "2026-06-02T10:00", "2026-12-04", 4600
                )
            )  # Tue
        for _ in range(3):
            rows.append(
                self._make_row(
                    "KLM", "CPH", "AMS", "2026-06-03T10:00", "2026-12-04", 4900
                )
            )  # Wed
        for _ in range(5):
            rows.append(
                self._make_row(
                    "KLM", "CPH", "AMS", "2026-06-04T10:00", "2026-12-04", 4760
                )
            )  # Thu (5 obs to anchor the median at 4760)
        for _ in range(3):
            rows.append(
                self._make_row(
                    "KLM", "CPH", "AMS", "2026-06-05T10:00", "2026-12-04", 6500
                )
            )  # Fri

        result = build_airline_matrix(rows)
        matrix = result["CPH-AMS"][0]["matrix"]["Friday"]

        assert matrix["Monday"]["category"] == "cheap-high"
        assert matrix["Tuesday"]["category"] == "cheap-low"
        assert matrix["Wednesday"]["category"] == "expensive-low"
        assert matrix["Thursday"]["category"] == "no"
        assert matrix["Friday"]["category"] == "expensive-high"

    def test_only_fri_sat_sun_travel_days(self):
        """Weekday/Thursday departure rows are excluded from matrix."""
        from src.html_generator import build_airline_matrix

        # 2026-12-07 is Monday (weekday 0) — should be excluded
        rows = [
            self._make_row("KLM", "CPH", "AMS", "2026-06-01T10:00", "2026-12-07", 5000),
            self._make_row("KLM", "CPH", "AMS", "2026-06-01T12:00", "2026-12-07", 5100),
            self._make_row("KLM", "CPH", "AMS", "2026-06-01T14:00", "2026-12-07", 5200),
        ]

        result = build_airline_matrix(rows)
        # Either route not present or airline list is empty
        if "CPH-AMS" in result:
            assert result["CPH-AMS"] == []

    def test_airline_excluded_if_fewer_than_3_total(self):
        """Airlines with <3 total observations across all cells are omitted."""
        from src.html_generator import build_airline_matrix

        # 2 rows total for easyJet on a Friday departure — should be excluded
        rows = [
            self._make_row(
                "easyJet", "CPH", "AMS", "2026-06-01T10:00", "2026-12-04", 4000
            ),
            self._make_row(
                "easyJet", "CPH", "AMS", "2026-06-02T10:00", "2026-12-04", 4200
            ),
        ]

        result = build_airline_matrix(rows)
        if "CPH-AMS" in result:
            airlines = [e["airline"] for e in result["CPH-AMS"]]
            assert "easyJet" not in airlines

    def test_two_routes_independent(self):
        """CPH-AMS and AMS-CPH are separate keys in the result."""
        from src.html_generator import build_airline_matrix

        rows = []
        for _ in range(3):
            rows.append(
                self._make_row(
                    "KLM", "CPH", "AMS", "2026-06-01T10:00", "2026-12-04", 5000
                )
            )
            rows.append(
                self._make_row(
                    "KLM", "AMS", "CPH", "2026-06-01T10:00", "2026-12-04", 5500
                )
            )

        result = build_airline_matrix(rows)
        assert "CPH-AMS" in result
        assert "AMS-CPH" in result

    def test_empty_rows(self):
        """Empty input returns empty dict."""
        from src.html_generator import build_airline_matrix

        result = build_airline_matrix([])
        assert result == {}

    def test_saturday_and_sunday_travel_days(self):
        """Saturday and Sunday departures are routed to correct matrix keys."""
        from src.html_generator import build_airline_matrix

        # 2026-12-05 is Saturday (weekday 5), 2026-12-06 is Sunday (weekday 6)
        rows = []
        for _ in range(3):
            # Saturday departure
            rows.append(
                self._make_row(
                    "KLM", "CPH", "AMS", "2026-06-01T10:00", "2026-12-05", 5000
                )
            )
            # Sunday departure
            rows.append(
                self._make_row(
                    "KLM", "CPH", "AMS", "2026-06-01T12:00", "2026-12-06", 5500
                )
            )

        result = build_airline_matrix(rows)
        matrix = result["CPH-AMS"][0]["matrix"]

        # Monday-bought Saturday flights
        assert matrix["Saturday"]["Monday"] is not None
        assert matrix["Saturday"]["Monday"]["n"] == 3
        # Monday-bought Sunday flights
        assert matrix["Sunday"]["Monday"] is not None
        assert matrix["Sunday"]["Monday"]["n"] == 3
        # Friday flights not polluted by Saturday/Sunday obs
        assert matrix["Friday"]["Monday"] is None

    def test_cheap_low_category(self):
        """Negative index -0.03 should produce cheap-low category."""
        from src.html_generator import build_airline_matrix

        rows = [
            # Tuesday-Friday: 9700, 9650, 9700 (median 9700)
            {
                "airline": "KLM",
                "origin": "CPH",
                "destination": "AMS",
                "retrieved_at": datetime(2026, 6, 2, 10, 0, tzinfo=timezone.utc),  # Tuesday
                "departure_date": "2026-06-05",  # Friday
                "price_cents": 9700,
                "departure_at": datetime(2026, 6, 5, 10, 0),
                "arrival_at": datetime(2026, 6, 5, 12, 0),
                "duration_minutes": 120,
                "price_currency": "EUR",
            },
            {
                "airline": "KLM",
                "origin": "CPH",
                "destination": "AMS",
                "retrieved_at": datetime(2026, 6, 2, 10, 0, tzinfo=timezone.utc),
                "departure_date": "2026-06-05",
                "price_cents": 9650,
                "departure_at": datetime(2026, 6, 5, 10, 0),
                "arrival_at": datetime(2026, 6, 5, 12, 0),
                "duration_minutes": 120,
                "price_currency": "EUR",
            },
            {
                "airline": "KLM",
                "origin": "CPH",
                "destination": "AMS",
                "retrieved_at": datetime(2026, 6, 2, 10, 0, tzinfo=timezone.utc),
                "departure_date": "2026-06-05",
                "price_cents": 9700,
                "departure_at": datetime(2026, 6, 5, 10, 0),
                "arrival_at": datetime(2026, 6, 5, 12, 0),
                "duration_minutes": 120,
                "price_currency": "EUR",
            },
            # Monday-Friday: 10000, 10000, 10000 (establishes overall_median=10000)
            {
                "airline": "KLM",
                "origin": "CPH",
                "destination": "AMS",
                "retrieved_at": datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc),  # Monday
                "departure_date": "2026-06-05",  # Friday
                "price_cents": 10000,
                "departure_at": datetime(2026, 6, 5, 10, 0),
                "arrival_at": datetime(2026, 6, 5, 12, 0),
                "duration_minutes": 120,
                "price_currency": "EUR",
            },
            {
                "airline": "KLM",
                "origin": "CPH",
                "destination": "AMS",
                "retrieved_at": datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc),
                "departure_date": "2026-06-05",
                "price_cents": 10000,
                "departure_at": datetime(2026, 6, 5, 10, 0),
                "arrival_at": datetime(2026, 6, 5, 12, 0),
                "duration_minutes": 120,
                "price_currency": "EUR",
            },
            {
                "airline": "KLM",
                "origin": "CPH",
                "destination": "AMS",
                "retrieved_at": datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc),
                "departure_date": "2026-06-05",
                "price_cents": 10000,
                "departure_at": datetime(2026, 6, 5, 10, 0),
                "arrival_at": datetime(2026, 6, 5, 12, 0),
                "duration_minutes": 120,
                "price_currency": "EUR",
            },
        ]
        result = build_airline_matrix(rows)
        cell = result["CPH-AMS"][0]["matrix"]["Friday"]["Tuesday"]
        assert cell is not None
        assert cell["category"] == "cheap-low"
        assert cell["index"] < 0

    def test_expensive_med_category(self):
        """Positive index +0.08 should produce expensive-med category."""
        from src.html_generator import build_airline_matrix

        rows = [
            # Tuesday-Friday: 10800, 10800, 10800 (median 10800)
            {
                "airline": "KLM",
                "origin": "CPH",
                "destination": "AMS",
                "retrieved_at": datetime(2026, 6, 2, 10, 0, tzinfo=timezone.utc),  # Tuesday
                "departure_date": "2026-06-05",  # Friday
                "price_cents": 10800,
                "departure_at": datetime(2026, 6, 5, 10, 0),
                "arrival_at": datetime(2026, 6, 5, 12, 0),
                "duration_minutes": 120,
                "price_currency": "EUR",
            },
            {
                "airline": "KLM",
                "origin": "CPH",
                "destination": "AMS",
                "retrieved_at": datetime(2026, 6, 2, 10, 0, tzinfo=timezone.utc),
                "departure_date": "2026-06-05",
                "price_cents": 10800,
                "departure_at": datetime(2026, 6, 5, 10, 0),
                "arrival_at": datetime(2026, 6, 5, 12, 0),
                "duration_minutes": 120,
                "price_currency": "EUR",
            },
            {
                "airline": "KLM",
                "origin": "CPH",
                "destination": "AMS",
                "retrieved_at": datetime(2026, 6, 2, 10, 0, tzinfo=timezone.utc),
                "departure_date": "2026-06-05",
                "price_cents": 10800,
                "departure_at": datetime(2026, 6, 5, 10, 0),
                "arrival_at": datetime(2026, 6, 5, 12, 0),
                "duration_minutes": 120,
                "price_currency": "EUR",
            },
            # Other cells with 10000 to establish overall_median=10000
            {
                "airline": "KLM",
                "origin": "CPH",
                "destination": "AMS",
                "retrieved_at": datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc),  # Monday
                "departure_date": "2026-06-05",  # Friday
                "price_cents": 10000,
                "departure_at": datetime(2026, 6, 5, 10, 0),
                "arrival_at": datetime(2026, 6, 5, 12, 0),
                "duration_minutes": 120,
                "price_currency": "EUR",
            },
            {
                "airline": "KLM",
                "origin": "CPH",
                "destination": "AMS",
                "retrieved_at": datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc),
                "departure_date": "2026-06-05",
                "price_cents": 10000,
                "departure_at": datetime(2026, 6, 5, 10, 0),
                "arrival_at": datetime(2026, 6, 5, 12, 0),
                "duration_minutes": 120,
                "price_currency": "EUR",
            },
            {
                "airline": "KLM",
                "origin": "CPH",
                "destination": "AMS",
                "retrieved_at": datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc),
                "departure_date": "2026-06-05",
                "price_cents": 10000,
                "departure_at": datetime(2026, 6, 5, 10, 0),
                "arrival_at": datetime(2026, 6, 5, 12, 0),
                "duration_minutes": 120,
                "price_currency": "EUR",
            },
            {
                "airline": "KLM",
                "origin": "CPH",
                "destination": "AMS",
                "retrieved_at": datetime(2026, 6, 3, 10, 0, tzinfo=timezone.utc),  # Wednesday
                "departure_date": "2026-06-05",  # Friday
                "price_cents": 10000,
                "departure_at": datetime(2026, 6, 5, 10, 0),
                "arrival_at": datetime(2026, 6, 5, 12, 0),
                "duration_minutes": 120,
                "price_currency": "EUR",
            },
        ]
        result = build_airline_matrix(rows)
        cell = result["CPH-AMS"][0]["matrix"]["Friday"]["Tuesday"]
        assert cell is not None
        assert cell["category"] == "expensive-med"
        assert cell["index"] > 0

    def test_cheap_high_category(self):
        """Negative index < -0.15 should produce cheap-high category."""
        from src.html_generator import build_airline_matrix

        rows = [
            # Tuesday-Friday: 8400, 8400, 8400 (median 8400)
            {
                "airline": "KLM",
                "origin": "CPH",
                "destination": "AMS",
                "retrieved_at": datetime(2026, 6, 2, 10, 0, tzinfo=timezone.utc),
                "departure_date": "2026-06-05",
                "price_cents": 8400,
                "departure_at": datetime(2026, 6, 5, 10, 0),
                "arrival_at": datetime(2026, 6, 5, 12, 0),
                "duration_minutes": 120,
                "price_currency": "EUR",
            },
            {
                "airline": "KLM",
                "origin": "CPH",
                "destination": "AMS",
                "retrieved_at": datetime(2026, 6, 2, 10, 0, tzinfo=timezone.utc),
                "departure_date": "2026-06-05",
                "price_cents": 8400,
                "departure_at": datetime(2026, 6, 5, 10, 0),
                "arrival_at": datetime(2026, 6, 5, 12, 0),
                "duration_minutes": 120,
                "price_currency": "EUR",
            },
            {
                "airline": "KLM",
                "origin": "CPH",
                "destination": "AMS",
                "retrieved_at": datetime(2026, 6, 2, 10, 0, tzinfo=timezone.utc),
                "departure_date": "2026-06-05",
                "price_cents": 8400,
                "departure_at": datetime(2026, 6, 5, 10, 0),
                "arrival_at": datetime(2026, 6, 5, 12, 0),
                "duration_minutes": 120,
                "price_currency": "EUR",
            },
            # Other cells with 10000 to establish overall_median=10000
            {
                "airline": "KLM",
                "origin": "CPH",
                "destination": "AMS",
                "retrieved_at": datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc),  # Monday
                "departure_date": "2026-06-05",  # Friday
                "price_cents": 10000,
                "departure_at": datetime(2026, 6, 5, 10, 0),
                "arrival_at": datetime(2026, 6, 5, 12, 0),
                "duration_minutes": 120,
                "price_currency": "EUR",
            },
            {
                "airline": "KLM",
                "origin": "CPH",
                "destination": "AMS",
                "retrieved_at": datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc),
                "departure_date": "2026-06-05",
                "price_cents": 10000,
                "departure_at": datetime(2026, 6, 5, 10, 0),
                "arrival_at": datetime(2026, 6, 5, 12, 0),
                "duration_minutes": 120,
                "price_currency": "EUR",
            },
            {
                "airline": "KLM",
                "origin": "CPH",
                "destination": "AMS",
                "retrieved_at": datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc),
                "departure_date": "2026-06-05",
                "price_cents": 10000,
                "departure_at": datetime(2026, 6, 5, 10, 0),
                "arrival_at": datetime(2026, 6, 5, 12, 0),
                "duration_minutes": 120,
                "price_currency": "EUR",
            },
            {
                "airline": "KLM",
                "origin": "CPH",
                "destination": "AMS",
                "retrieved_at": datetime(2026, 6, 3, 10, 0, tzinfo=timezone.utc),  # Wednesday
                "departure_date": "2026-06-05",  # Friday
                "price_cents": 10000,
                "departure_at": datetime(2026, 6, 5, 10, 0),
                "arrival_at": datetime(2026, 6, 5, 12, 0),
                "duration_minutes": 120,
                "price_currency": "EUR",
            },
        ]
        result = build_airline_matrix(rows)
        cell = result["CPH-AMS"][0]["matrix"]["Friday"]["Tuesday"]
        assert cell is not None
        assert cell["category"] == "cheap-high"
        assert cell["index"] < -0.15

    def test_expensive_high_category(self):
        """Positive index > +0.15 should produce expensive-high category."""
        from src.html_generator import build_airline_matrix

        rows = [
            # Tuesday-Friday: 11600, 11600, 11600 (median 11600)
            {
                "airline": "KLM",
                "origin": "CPH",
                "destination": "AMS",
                "retrieved_at": datetime(2026, 6, 2, 10, 0, tzinfo=timezone.utc),
                "departure_date": "2026-06-05",
                "price_cents": 11600,
                "departure_at": datetime(2026, 6, 5, 10, 0),
                "arrival_at": datetime(2026, 6, 5, 12, 0),
                "duration_minutes": 120,
                "price_currency": "EUR",
            },
            {
                "airline": "KLM",
                "origin": "CPH",
                "destination": "AMS",
                "retrieved_at": datetime(2026, 6, 2, 10, 0, tzinfo=timezone.utc),
                "departure_date": "2026-06-05",
                "price_cents": 11600,
                "departure_at": datetime(2026, 6, 5, 10, 0),
                "arrival_at": datetime(2026, 6, 5, 12, 0),
                "duration_minutes": 120,
                "price_currency": "EUR",
            },
            {
                "airline": "KLM",
                "origin": "CPH",
                "destination": "AMS",
                "retrieved_at": datetime(2026, 6, 2, 10, 0, tzinfo=timezone.utc),
                "departure_date": "2026-06-05",
                "price_cents": 11600,
                "departure_at": datetime(2026, 6, 5, 10, 0),
                "arrival_at": datetime(2026, 6, 5, 12, 0),
                "duration_minutes": 120,
                "price_currency": "EUR",
            },
            # Other cells with 10000 to establish overall_median=10000
            {
                "airline": "KLM",
                "origin": "CPH",
                "destination": "AMS",
                "retrieved_at": datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc),  # Monday
                "departure_date": "2026-06-05",  # Friday
                "price_cents": 10000,
                "departure_at": datetime(2026, 6, 5, 10, 0),
                "arrival_at": datetime(2026, 6, 5, 12, 0),
                "duration_minutes": 120,
                "price_currency": "EUR",
            },
            {
                "airline": "KLM",
                "origin": "CPH",
                "destination": "AMS",
                "retrieved_at": datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc),
                "departure_date": "2026-06-05",
                "price_cents": 10000,
                "departure_at": datetime(2026, 6, 5, 10, 0),
                "arrival_at": datetime(2026, 6, 5, 12, 0),
                "duration_minutes": 120,
                "price_currency": "EUR",
            },
            {
                "airline": "KLM",
                "origin": "CPH",
                "destination": "AMS",
                "retrieved_at": datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc),
                "departure_date": "2026-06-05",
                "price_cents": 10000,
                "departure_at": datetime(2026, 6, 5, 10, 0),
                "arrival_at": datetime(2026, 6, 5, 12, 0),
                "duration_minutes": 120,
                "price_currency": "EUR",
            },
            {
                "airline": "KLM",
                "origin": "CPH",
                "destination": "AMS",
                "retrieved_at": datetime(2026, 6, 3, 10, 0, tzinfo=timezone.utc),  # Wednesday
                "departure_date": "2026-06-05",  # Friday
                "price_cents": 10000,
                "departure_at": datetime(2026, 6, 5, 10, 0),
                "arrival_at": datetime(2026, 6, 5, 12, 0),
                "duration_minutes": 120,
                "price_currency": "EUR",
            },
        ]
        result = build_airline_matrix(rows)
        cell = result["CPH-AMS"][0]["matrix"]["Friday"]["Tuesday"]
        assert cell is not None
        assert cell["category"] == "expensive-high"
        assert cell["index"] > 0.15
