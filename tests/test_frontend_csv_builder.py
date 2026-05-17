"""Tests for src.frontend_csv_builder.

NOTE: All time fixtures in this file use the real prose format produced by
fast_flights (e.g. "7:30 PM on Fri, Jun 19"). Existing DB-layer tests use
simplified "08:00" strings, but those do not reflect what the scraper
actually returns and would mask real parse failures here.
"""

import csv
import logging
import os
from datetime import datetime, timezone

import pytest

from src.frontend_csv_builder import (
    BUILD_ALL_UNPARSEABLE,
    BUILD_HEADER_INVALID,
    BUILD_INPUT_MISSING,
    BUILD_OK,
    OUTPUT_COLUMNS,
    REQUIRED_INPUT_COLUMNS,
    build,
    compute_duration_minutes,
    parse_prose_datetime,
    parse_retrieved_at,
    parse_time_of_day,
    slim_row,
    sort_rows,
)


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


def test_parse_prose_datetime_simple():
    assert parse_prose_datetime("7:30 PM on Fri, Jun 19", 2026) == datetime(
        2026, 6, 19, 19, 30
    )


def test_parse_prose_datetime_overnight():
    assert parse_prose_datetime("9:45 AM on Sat, Jun 20", 2026) == datetime(
        2026, 6, 20, 9, 45
    )


def test_parse_prose_datetime_all_months():
    months = {
        "Jan": 1,
        "Feb": 2,
        "Mar": 3,
        "Apr": 4,
        "May": 5,
        "Jun": 6,
        "Jul": 7,
        "Aug": 8,
        "Sep": 9,
        "Oct": 10,
        "Nov": 11,
        "Dec": 12,
    }
    for name, num in months.items():
        result = parse_prose_datetime(f"6:00 AM on Mon, {name} 5", 2026)
        assert result.month == num, name


def test_parse_prose_datetime_empty_raises():
    with pytest.raises(ValueError):
        parse_prose_datetime("", 2026)


def test_parse_prose_datetime_unknown_month_raises():
    with pytest.raises(ValueError):
        parse_prose_datetime("9:45 AM on Sat, Foo 20", 2026)


def test_parse_prose_datetime_missing_date_raises():
    with pytest.raises(ValueError):
        parse_prose_datetime("9:45 AM", 2026)


def test_compute_duration_minutes_short():
    dep = datetime(2026, 6, 19, 19, 30)
    arr = datetime(2026, 6, 19, 21, 0)
    assert compute_duration_minutes(dep, arr) == 90


def test_compute_duration_minutes_overnight():
    # 17:00 Fri -> 09:45 Sat = 16h 45m = 1005 minutes. (The issue body cites
    # 945 as the example for this case, but the spec's defined formula
    # (arrival - departure).total_seconds() // 60 gives 1005.)
    dep = datetime(2026, 6, 19, 17, 0)
    arr = datetime(2026, 6, 20, 9, 45)
    assert compute_duration_minutes(dep, arr) == 1005


def test_compute_duration_minutes_zero():
    dep = datetime(2026, 6, 19, 19, 30)
    assert compute_duration_minutes(dep, dep) == 0


def _input_row(**overrides):
    base = {
        "retrieved_at": "2026-05-15T13:45:23.421566+00:00",
        "departure_date": "2026-06-19",
        "origin": "CPH",
        "destination": "AMS",
        "airline": "easyJet",
        "departure_time": "7:30 PM on Fri, Jun 19",
        "arrival_time": "9:00 PM on Fri, Jun 19",
        "price_amount": "9200",
        "price_currency": "EUR",
    }
    base.update(overrides)
    return base


def test_slim_row_happy_path():
    out = slim_row(_input_row())
    assert out == {
        "retrieved_at": "2026-05-15T13:45Z",
        "departure_date": "2026-06-19",
        "origin": "CPH",
        "destination": "AMS",
        "airline": "easyJet",
        "departure_at": "2026-06-19T19:30:00",
        "arrival_at": "2026-06-19T21:00:00",
        "duration_minutes": 90,
        "price_cents": 9200,
        "price_currency": "EUR",
    }


def test_slim_row_overnight_finnair():
    out = slim_row(
        _input_row(
            airline="Finnair",
            departure_time="5:00 PM on Fri, Jun 19",
            arrival_time="6:45 PM on Fri, Jun 19",
            price_amount="13400",
        )
    )
    assert out["arrival_at"] == "2026-06-19T18:45:00"
    assert out["duration_minutes"] == 105


def test_slim_row_cross_year_rollover():
    out = slim_row(
        _input_row(
            departure_date="2026-12-31",
            departure_time="11:30 PM on Wed, Dec 31",
            arrival_time="1:00 AM on Thu, Jan 1",
        )
    )
    # Arrival rolls into 2027.
    assert out["arrival_at"] == "2027-01-01T01:00:00"
    assert out["duration_minutes"] == 90


def test_slim_row_drops_duration_over_2_hours():
    out = slim_row(
        _input_row(
            departure_time="7:00 PM on Fri, Jun 19",
            arrival_time="9:01 PM on Fri, Jun 19",
        )
    )
    assert out is None


def test_slim_row_keeps_duration_equal_2_hours():
    out = slim_row(
        _input_row(
            departure_time="7:00 PM on Fri, Jun 19",
            arrival_time="9:00 PM on Fri, Jun 19",
        )
    )
    assert out is not None
    assert out["duration_minutes"] == 120


def test_build_dedupes_identical_rows(tmp_path):
    src_path = str(tmp_path / "in.csv")
    out = str(tmp_path / "out.csv")
    duplicate = _input_csv_row()
    _write_input(src_path, [duplicate, duplicate])
    written, status = build(src_path, out)
    assert status == BUILD_OK
    assert written == 1
    rows = _read_output(out)
    assert len(rows) == 1


def test_build_logs_skip_summary_once(tmp_path, caplog):
    src_path = str(tmp_path / "in.csv")
    out = str(tmp_path / "out.csv")
    _write_input(
        src_path,
        [
            _input_csv_row(departure_time="", arrival_time=""),
            _input_csv_row(),
        ],
    )
    with caplog.at_level(logging.INFO, logger="src.frontend_csv_builder"):
        written, status = build(src_path, out)
    assert status == BUILD_OK
    assert written == 1
    assert any(
        "missing time" in rec.message and "skipped" in rec.message
        for rec in caplog.records
    )
    assert not any("row " in rec.message for rec in caplog.records)


def test_slim_row_drops_empty_departure_time():
    assert slim_row(_input_row(departure_time="", arrival_time="")) is None


def test_slim_row_drops_only_departure_empty():
    assert (
        slim_row(_input_row(departure_time="", arrival_time="9:00 PM on Fri, Jun 19"))
        is None
    )


def test_slim_row_drops_only_arrival_empty():
    assert slim_row(_input_row(arrival_time="")) is None


def test_slim_row_passes_empty_airline_through():
    out = slim_row(_input_row(airline=""))
    assert out is not None
    assert out["airline"] == ""


def test_slim_row_preserves_airline_with_comma():
    out = slim_row(_input_row(airline="Air France, KLM"))
    assert out["airline"] == "Air France, KLM"


def test_slim_row_drops_price_zero():
    assert slim_row(_input_row(price_amount="0")) is None


def test_slim_row_drops_price_empty():
    assert slim_row(_input_row(price_amount="")) is None


def test_slim_row_drops_price_non_integer():
    assert slim_row(_input_row(price_amount="abc")) is None


def test_slim_row_drops_malformed_arrival():
    assert slim_row(_input_row(arrival_time="sometime Fri")) is None


def test_slim_row_retrieved_at_uses_z_suffix_string():
    out = slim_row(_input_row())
    # Pin the literal format; .isoformat() on Python 3.9 produces '+00:00', not 'Z'.
    assert out["retrieved_at"] == "2026-05-15T13:45Z"
    assert "+00:00" not in out["retrieved_at"]


def _out_row(**overrides):
    base = {
        "retrieved_at": "2026-05-15T13:45Z",
        "departure_date": "2026-06-19",
        "origin": "CPH",
        "destination": "AMS",
        "airline": "easyJet",
        "departure_at": "2026-06-19T19:30:00",
        "arrival_at": "2026-06-19T21:00:00",
        "duration_minutes": 90,
        "price_cents": 9200,
        "price_currency": "EUR",
    }
    base.update(overrides)
    return base


def test_sort_rows_by_departure_date():
    rows = [
        _out_row(departure_date="2026-06-20"),
        _out_row(departure_date="2026-06-19"),
    ]
    result = sort_rows(rows)
    assert [r["departure_date"] for r in result] == ["2026-06-19", "2026-06-20"]


def test_sort_rows_full_key_order():
    rows = [
        _out_row(
            departure_date="2026-06-19",
            origin="CPH",
            destination="AMS",
            retrieved_at="2026-05-15T13:45Z",
            price_cents=11000,
            airline="KLM",
        ),
        _out_row(
            departure_date="2026-06-19",
            origin="CPH",
            destination="AMS",
            retrieved_at="2026-05-15T13:45Z",
            price_cents=10700,
            airline="Norwegian",
        ),
        _out_row(
            departure_date="2026-06-19",
            origin="AMS",
            destination="CPH",
            retrieved_at="2026-05-15T13:45Z",
            price_cents=9000,
            airline="easyJet",
        ),
    ]
    result = sort_rows(rows)
    # AMS->CPH first (origin ASC).
    assert (result[0]["origin"], result[0]["destination"]) == ("AMS", "CPH")
    # Then CPH->AMS, ordered by price ASC.
    assert result[1]["price_cents"] == 10700
    assert result[2]["price_cents"] == 11000


def test_sort_rows_airline_tiebreaker():
    # Same key prefix through price_cents; only airline differs.
    rows = [
        _out_row(airline="Norwegian"),
        _out_row(airline="KLM"),
        _out_row(airline="easyJet"),
    ]
    result = sort_rows(rows)
    assert [r["airline"] for r in result] == ["KLM", "Norwegian", "easyJet"]


def test_sort_rows_is_stable_and_deterministic():
    rows = [_out_row(airline="X") for _ in range(50)]
    assert sort_rows(rows) == sort_rows(list(reversed(rows)))


def _write_input(path, rows, columns=None):
    columns = columns or REQUIRED_INPUT_COLUMNS
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def _read_output(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def _input_csv_row(**overrides):
    return _input_row(**overrides)


def test_build_input_missing(tmp_path):
    out = str(tmp_path / "out.csv")
    written, status = build(str(tmp_path / "missing.csv"), out)
    assert status == BUILD_INPUT_MISSING
    assert written == 0
    assert not os.path.exists(out)


def test_build_header_invalid(tmp_path):
    src_path = str(tmp_path / "in.csv")
    out = str(tmp_path / "out.csv")
    bad_columns = [c for c in REQUIRED_INPUT_COLUMNS if c != "price_amount"]
    _write_input(src_path, [], columns=bad_columns)
    written, status = build(src_path, out)
    assert status == BUILD_HEADER_INVALID
    assert written == 0
    assert not os.path.exists(out)


def test_build_empty_input_writes_header_only(tmp_path):
    src_path = str(tmp_path / "in.csv")
    out = str(tmp_path / "out.csv")
    _write_input(src_path, [])
    written, status = build(src_path, out)
    assert status == BUILD_OK
    assert written == 0
    with open(out) as f:
        contents = f.read()
    assert contents == ",".join(OUTPUT_COLUMNS) + "\n"


def test_build_happy_path_single_row(tmp_path):
    src_path = str(tmp_path / "in.csv")
    out = str(tmp_path / "out.csv")
    _write_input(src_path, [_input_csv_row()])
    written, status = build(src_path, out)
    assert status == BUILD_OK
    assert written == 1
    rows = _read_output(out)
    assert len(rows) == 1
    assert rows[0]["retrieved_at"] == "2026-05-15T13:45Z"
    assert rows[0]["price_cents"] == "9200"
    assert rows[0]["price_currency"] == "EUR"
    assert list(rows[0].keys()) == OUTPUT_COLUMNS


def test_build_within_snapshot_near_duplicate_kept(tmp_path):
    # Same retrieved_at + route + date + airline + dep/arr + currency, two prices.
    src_path = str(tmp_path / "in.csv")
    out = str(tmp_path / "out.csv")
    _write_input(
        src_path,
        [
            _input_csv_row(price_amount="9200"),
            _input_csv_row(price_amount="11000"),
        ],
    )
    _, status = build(src_path, out)
    assert status == BUILD_OK
    rows = _read_output(out)
    assert [r["price_cents"] for r in rows] == ["9200", "11000"]


def test_build_norwegian_klm_collision_kept(tmp_path):
    src_path = str(tmp_path / "in.csv")
    out = str(tmp_path / "out.csv")
    _write_input(
        src_path,
        [
            _input_csv_row(
                airline="Norwegian",
                price_amount="10700",
                departure_time="4:30 PM on Fri, Jun 19",
                arrival_time="5:55 PM on Fri, Jun 19",
            ),
            _input_csv_row(
                airline="KLM",
                price_amount="11000",
                departure_time="4:30 PM on Fri, Jun 19",
                arrival_time="5:55 PM on Fri, Jun 19",
            ),
        ],
    )
    _, status = build(src_path, out)
    assert status == BUILD_OK
    rows = _read_output(out)
    assert {r["airline"] for r in rows} == {"Norwegian", "KLM"}


def test_build_logs_skip_summary_on_parse_error(tmp_path, caplog):
    src_path = str(tmp_path / "in.csv")
    out = str(tmp_path / "out.csv")
    _write_input(
        src_path,
        [
            _input_csv_row(arrival_time="sometime Fri"),  # malformed
            _input_csv_row(),  # ok
        ],
    )
    with caplog.at_level(logging.INFO, logger="src.frontend_csv_builder"):
        written, status = build(src_path, out)
    assert status == BUILD_OK
    assert written == 1
    rows = _read_output(out)
    assert len(rows) == 1
    assert any(
        "parse error" in rec.message and "skipped" in rec.message
        for rec in caplog.records
    )
    assert not any("row " in rec.message for rec in caplog.records)


def test_build_logs_skip_summary_on_invalid_price(tmp_path, caplog):
    src_path = str(tmp_path / "in.csv")
    out = str(tmp_path / "out.csv")
    _write_input(src_path, [_input_csv_row(price_amount="0"), _input_csv_row()])
    with caplog.at_level(logging.INFO, logger="src.frontend_csv_builder"):
        written, status = build(src_path, out)
    assert status == BUILD_OK
    assert written == 1
    assert any(
        "invalid price" in rec.message and "skipped" in rec.message
        for rec in caplog.records
    )
    assert not any("row " in rec.message for rec in caplog.records)


def test_build_all_rows_unparseable_returns_status(tmp_path):
    src_path = str(tmp_path / "in.csv")
    out = str(tmp_path / "out.csv")
    _write_input(src_path, [_input_csv_row(arrival_time="garbage")])
    written, status = build(src_path, out)
    assert status == BUILD_ALL_UNPARSEABLE
    assert written == 0


def test_build_sort_order_across_mixed_input(tmp_path):
    src_path = str(tmp_path / "in.csv")
    out = str(tmp_path / "out.csv")
    _write_input(
        src_path,
        [
            _input_csv_row(
                departure_date="2026-06-20",
                airline="X",
                price_amount="9000",
                departure_time="7:00 PM on Sat, Jun 20",
                arrival_time="8:30 PM on Sat, Jun 20",
            ),
            _input_csv_row(
                departure_date="2026-06-19",
                airline="Z",
                price_amount="9000",
                departure_time="7:00 PM on Fri, Jun 19",
                arrival_time="8:30 PM on Fri, Jun 19",
            ),
            _input_csv_row(
                departure_date="2026-06-19",
                airline="A",
                price_amount="8000",
                departure_time="7:00 PM on Fri, Jun 19",
                arrival_time="8:30 PM on Fri, Jun 19",
            ),
        ],
    )
    build(src_path, out)
    rows = _read_output(out)
    assert [r["departure_date"] for r in rows] == [
        "2026-06-19",
        "2026-06-19",
        "2026-06-20",
    ]
    assert [r["airline"] for r in rows] == ["A", "Z", "X"]


def test_build_unknown_airline_kept(tmp_path):
    src_path = str(tmp_path / "in.csv")
    out = str(tmp_path / "out.csv")
    _write_input(src_path, [_input_csv_row(airline="Some Random Carrier")])
    build(src_path, out)
    rows = _read_output(out)
    assert rows[0]["airline"] == "Some Random Carrier"


def test_build_airline_with_comma_round_trips(tmp_path):
    src_path = str(tmp_path / "in.csv")
    out = str(tmp_path / "out.csv")
    _write_input(src_path, [_input_csv_row(airline="Air France, KLM")])
    build(src_path, out)
    rows = _read_output(out)
    assert rows[0]["airline"] == "Air France, KLM"


def test_build_uses_lf_line_endings(tmp_path):
    src_path = str(tmp_path / "in.csv")
    out = str(tmp_path / "out.csv")
    _write_input(src_path, [_input_csv_row()])
    build(src_path, out)
    with open(out, "rb") as f:
        contents = f.read()
    assert b"\r\n" not in contents
    assert contents.count(b"\n") == 2  # header + 1 row


def test_build_large_input_completes(tmp_path):
    """Modest scale (1k rows) — full perf left to manual runs against the live file."""
    src_path = str(tmp_path / "in.csv")
    out = str(tmp_path / "out.csv")
    _write_input(src_path, [_input_csv_row() for _ in range(1000)])
    written, status = build(src_path, out)
    assert status == BUILD_OK
    assert written == 1


# --- CLI tests ---

import subprocess  # noqa: E402
import sys  # noqa: E402


def _project_root():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))


def _run_cli(args, cwd=None):
    return subprocess.run(
        [sys.executable, "scripts/build_frontend_csv.py", *args],
        cwd=cwd or _project_root(),
        capture_output=True,
        text=True,
    )


def test_cli_missing_input_exits_2(tmp_path):
    out = str(tmp_path / "out.csv")
    result = _run_cli(["--input", str(tmp_path / "nope.csv"), "--output", out])
    assert result.returncode == 2


def test_cli_header_invalid_exits_3(tmp_path):
    src_path = str(tmp_path / "in.csv")
    out = str(tmp_path / "out.csv")
    bad_columns = [c for c in REQUIRED_INPUT_COLUMNS if c != "price_amount"]
    _write_input(src_path, [], columns=bad_columns)
    result = _run_cli(["--input", src_path, "--output", out])
    assert result.returncode == 3


def test_cli_all_unparseable_exits_4(tmp_path):
    src_path = str(tmp_path / "in.csv")
    out = str(tmp_path / "out.csv")
    _write_input(src_path, [_input_csv_row(arrival_time="garbage")])
    result = _run_cli(["--input", src_path, "--output", out])
    assert result.returncode == 4


def test_cli_happy_path_exits_0(tmp_path):
    src_path = str(tmp_path / "in.csv")
    out = str(tmp_path / "out.csv")
    _write_input(src_path, [_input_csv_row()])
    result = _run_cli(["--input", src_path, "--output", out])
    assert result.returncode == 0
    assert os.path.exists(out)


def test_cli_defaults_documented_in_help():
    result = _run_cli(["--help"])
    assert result.returncode == 0
    assert "data/flights_export.csv" in result.stdout
    assert "data/flights_frontend.csv" in result.stdout
