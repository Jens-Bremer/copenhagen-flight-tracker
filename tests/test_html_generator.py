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

    html = render_html(metadata={}, calendar={}, flights={}, analysis={}, summary={})
    all_scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.S)
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

    html = render_html(metadata={}, calendar={}, flights={}, analysis={}, summary={})
    all_scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.S)
    assert all_scripts
    app_js = all_scripts[-1]

    assert 'id="normprog-chart"' in html, (
        'HTML template must include <canvas id="normprog-chart"> for the '
        "normalised price progression panel"
    )
    assert "normalized_price_progression" in app_js, (
        "app.js must reference normalized_price_progression to render the chart"
    )


def test_timeheat_panel_rendered_in_html():
    """The rendered HTML must contain two heatmap canvas elements and the
    JS must reference time_of_day_matrix to populate them."""
    import re

    html = render_html(metadata={}, calendar={}, flights={}, analysis={}, summary={})
    all_scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.S)
    assert all_scripts
    app_js = all_scripts[-1]

    # Canvas elements for the two heatmap panels
    assert 'id="timeheat-out"' in html, (
        'HTML template must include <canvas id="timeheat-out"> for CPH-AMS heatmap'
    )
    assert 'id="timeheat-back"' in html, (
        'HTML template must include <canvas id="timeheat-back"> for AMS-CPH heatmap'
    )
    # JS must read time_of_day_matrix from the analysis data
    assert "time_of_day_matrix" in app_js, (
        "app.js must reference time_of_day_matrix to render the heatmap cells"
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


def test_format_price_uses_whole_euros_not_decimal():
    """All price values rendered by app.js must use whole euros (Math.round),
    not two-decimal-place formatting (.toFixed(2)).

    Prices are stored as integer cents in the JSON blobs and divided by 100
    in JS.  Using .toFixed(2) produces strings like '€161.00'; the correct
    output is '€161'.  This test checks the inlined app.js script for the
    presence of the correct pattern.
    """
    import re

    html = render_html(metadata={}, calendar={}, flights={}, analysis={}, summary={})
    # app.js is always the last <script> tag in the template (Chart.js comes before it).
    # We must not match Chart.js, which also uses .toFixed(2) internally.
    all_scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.S)
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

    html = render_html(metadata={}, calendar={}, flights={}, analysis={}, summary={})
    # app.js is always the last <script> tag in the template.
    all_scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.S)
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
    """DOW and month bar charts must colour bars with priceTint() (soft
    green→red alpha scale) rather than the hard-coded --color-green-ahead /
    --color-orange pair, which renders as harsh dark/solid fills.

    priceTint() returns rgba values at 0.32 alpha, matching the calendar
    heatmap's visual language and avoiding the near-black appearance of the
    dark-green CSS variable on some displays.
    """
    import re

    html = render_html(metadata={}, calendar={}, flights={}, analysis={}, summary={})
    all_scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.S)
    assert all_scripts, "No <script> blocks found in rendered HTML"
    app_js = all_scripts[-1]

    # Old hard-coded colours must be gone from bar chart backgroundColor.
    assert "'var(--color-green-ahead)'" not in app_js, (
        "makeBarChart must not use --color-green-ahead as a bar colour; "
        "use priceTint() for a consistent, gentle green-to-red scale"
    )
    assert "'var(--color-orange)'" not in app_js, (
        "makeBarChart must not use --color-orange as a bar colour; "
        "use priceTint() for a consistent palette"
    )
    # priceTint() must now be called inside renderFooterCharts/makeBarChart as
    # well as in renderCalendar — so it appears at least twice in the source.
    assert app_js.count("priceTint(") >= 2, (
        "Expected priceTint() to appear at least twice — once in renderCalendar "
        "and once inside renderFooterCharts/makeBarChart"
    )


def test_footer_charts_show_both_routes_as_grouped_bars():
    """DOW and month charts must show one grouped bar per route per x-axis item,
    not a single bar averaged across both routes.

    Each route gets a distinct colour defined in ROUTE_COLORS and appears in
    the chart legend so users can tell CPH-AMS from AMS-CPH at a glance.
    The old aggregate() helper that averaged both routes is replaced by a
    per-route dataset approach.
    """
    import re

    html = render_html(metadata={}, calendar={}, flights={}, analysis={}, summary={})
    all_scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.S)
    assert all_scripts, "No <script> blocks found in rendered HTML"
    app_js = all_scripts[-1]

    # A ROUTE_COLORS map must exist to colour each route's bars distinctly.
    assert "ROUTE_COLORS" in app_js, (
        "renderFooterCharts must define ROUTE_COLORS to assign a distinct "
        "colour per route in the grouped bar charts"
    )
    # The old aggregate() implementation averaged both routes into one value
    # per key — this must be gone, replaced by per-route datasets.
    assert "grouped[k].values.push" not in app_js, (
        "The aggregate() helper in renderFooterCharts must be removed; "
        "show one dataset per route instead of averaging them together"
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

    html = render_html(metadata={}, calendar={}, flights={}, analysis={}, summary={})
    all_scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.S)
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
    assert 'id="cal-prev"' in html, (
        "Previous-month button (id=cal-prev) missing from template"
    )
    assert 'id="cal-next"' in html, (
        "Next-month button (id=cal-next) missing from template"
    )
    assert 'id="cal-month-label"' in html, (
        "Month label (id=cal-month-label) missing from template"
    )


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


# ─── Issue #95: hero summary panel ───────────────────────────────────────────


def _app_js(html: str) -> str:
    """Extract the last <script> block (inlined app.js) from rendered HTML."""
    import re

    all_scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.S)
    assert all_scripts, "No <script> blocks found in rendered HTML"
    return all_scripts[-1]


def test_hero_panel_dom_ids_present_in_template():
    """Template must include the three hero card container IDs."""
    html = render_html(metadata={}, calendar={}, flights={}, analysis={}, summary={})
    assert 'id="hero-best-time"' in html, "hero-best-time container missing"
    assert 'id="hero-market"' in html, "hero-market container missing"
    assert 'id="hero-book-when"' in html, "hero-book-when container missing"


def test_hero_ids_in_required_dom_ids():
    """All three hero IDs must be asserted at boot via REQUIRED_DOM_IDS."""
    html = render_html(metadata={}, calendar={}, flights={}, analysis={}, summary={})
    js = _app_js(html)
    assert "'hero-best-time'" in js, "hero-best-time not in REQUIRED_DOM_IDS"
    assert "'hero-market'" in js, "hero-market not in REQUIRED_DOM_IDS"
    assert "'hero-book-when'" in js, "hero-book-when not in REQUIRED_DOM_IDS"


def test_render_hero_function_exists_and_called_from_render_all():
    """app.js must define renderHero() and call it from renderAll()."""
    html = render_html(metadata={}, calendar={}, flights={}, analysis={}, summary={})
    js = _app_js(html)
    assert "function renderHero" in js, "renderHero function not defined"
    assert "renderHero()" in js, "renderHero() not called from renderAll()"


def test_hero_best_time_reads_correct_analysis_fields():
    """renderHero must read best_time_to_visit with cheapest_month, cheapest_dow,
    and lowest_ever from DATA_ANALYSIS."""
    html = render_html(metadata={}, calendar={}, flights={}, analysis={}, summary={})
    js = _app_js(html)
    assert "best_time_to_visit" in js
    assert "cheapest_month" in js
    assert "cheapest_dow" in js
    assert "lowest_ever" in js


def test_hero_market_reads_market_direction_from_analysis():
    """renderHero must read market_direction.trend and market_direction.label."""
    html = render_html(metadata={}, calendar={}, flights={}, analysis={}, summary={})
    js = _app_js(html)
    assert "market_direction" in js
    # Must handle all three trend values
    assert "'down'" in js or '"down"' in js, "trend 'down' not handled"
    assert "'up'" in js or '"up"' in js, "trend 'up' not handled"
    assert "'stable'" in js or '"stable"' in js, "trend 'stable' not handled"


def test_hero_book_when_uses_sweet_spot_days():
    """renderHero must use sweet_spot_days from DATA_ANALYSIS for the booking card."""
    html = render_html(metadata={}, calendar={}, flights={}, analysis={}, summary={})
    js = _app_js(html)
    assert "sweet_spot_days" in js


def test_hero_css_classes_present_in_styles():
    """Generated HTML must include .hero-summary and .hero-card CSS rules."""
    html = render_html(metadata={}, calendar={}, flights={}, analysis={}, summary={})
    assert "hero-summary" in html
    assert "hero-card" in html


def test_hero_section_positioned_before_calendar_in_template():
    """Hero panel must appear in the template before the calendar section."""
    html = render_html(metadata={}, calendar={}, flights={}, analysis={}, summary={})
    hero_pos = html.find('id="hero-best-time"')
    calendar_pos = html.find('id="calendar"')
    assert hero_pos != -1, "hero-best-time not in HTML"
    assert calendar_pos != -1, "calendar not in HTML"
    assert hero_pos < calendar_pos, (
        "Hero panel must appear before the calendar in the HTML"
    )


def test_hero_shows_fallback_when_no_analysis_data():
    """renderHero must not crash and show a fallback when DATA_ANALYSIS is empty."""
    html = render_html(metadata={}, calendar={}, flights={}, analysis={}, summary={})
    js = _app_js(html)
    # There must be a fallback path (e.g. early return or "Not enough data" text)
    assert "Not enough data" in js or "fallback" in js.lower() or "return" in js, (
        "renderHero must handle empty analysis gracefully"
    )


# ─── Issue #96: per-flight trajectory arrows in drill-down ────────────────────


def test_drilldown_trajectory_arrow_rendered_when_not_null():
    """renderDrilldown must emit a .flight-row__trajectory span when trajectory
    is non-null, with an aria-label that names the direction and percentage."""
    html = render_html(metadata={}, calendar={}, flights={}, analysis={}, summary={})
    js = _app_js(html)
    assert "flight-row__trajectory" in js, (
        "renderDrilldown must include .flight-row__trajectory for trajectory arrows"
    )
    assert "trajectory" in js, (
        "renderDrilldown must read trajectory from flight data"
    )


def test_drilldown_trajectory_arrow_skipped_when_null():
    """No arrow span must be emitted when trajectory is null."""
    html = render_html(metadata={}, calendar={}, flights={}, analysis={}, summary={})
    js = _app_js(html)
    # The null guard must be present (some form of null/falsy check on trajectory)
    assert "trajectory" in js
    # There must be a conditional that avoids rendering when trajectory is null
    assert "f.trajectory" in js, (
        "JS must access f.trajectory to conditionally render the arrow"
    )


def test_drilldown_trajectory_arrow_has_aria_label():
    """Each trajectory arrow span must carry an aria-label for screen readers."""
    html = render_html(metadata={}, calendar={}, flights={}, analysis={}, summary={})
    js = _app_js(html)
    assert "aria-label" in js, (
        "trajectory arrow span must have an aria-label attribute"
    )


def test_drilldown_trajectory_arrow_colors_all_directions():
    """app.js must produce distinct CSS for each of the three directions."""
    html = render_html(metadata={}, calendar={}, flights={}, analysis={}, summary={})
    js = _app_js(html)
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
    html = render_html(metadata={}, calendar={}, flights={}, analysis={}, summary={})
    assert ".flight-row__trajectory" in html


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
