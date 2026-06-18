"""Tests for src.insights.flight_scatter.build_flight_scatter."""

from datetime import datetime, time, timedelta, timezone

import config
from src.insights.flight_scatter import build_flight_scatter

_NOW = datetime(2026, 6, 18, 22, 0, tzinfo=timezone.utc)


def _row(
    price_cents,
    *,
    retrieved,
    dep_date,
    dep_time="08:35",
    airline="KLM",
    origin="CPH",
    destination="AMS",
):
    """Build a load_rows-shaped observation dict.

    *retrieved* is a tz-aware datetime, *dep_date* a datetime.date.
    """
    hh, mm = (int(x) for x in dep_time.split(":"))
    departure_at = datetime.combine(dep_date, time(hh, mm))
    return {
        "origin": origin,
        "destination": destination,
        "airline": airline,
        "retrieved_at": retrieved,
        "departure_date": dep_date.isoformat(),
        "departure_at": departure_at,
        "arrival_at": departure_at + timedelta(minutes=90),
        "price_cents": price_cents,
    }


def test_happy_path_two_flights_same_route():
    dep = datetime(2026, 8, 4).date()  # a Tuesday
    r0 = datetime(2026, 6, 18, tzinfo=timezone.utc)
    rows = [
        # Flight A — KLM 08:35, two observations
        _row(15800, retrieved=r0 - timedelta(days=14), dep_date=dep),
        _row(14200, retrieved=r0, dep_date=dep),
        # Flight B — SAS 19:10, single observation
        _row(20000, retrieved=r0, dep_date=dep, dep_time="19:10", airline="SAS"),
    ]
    out = build_flight_scatter(rows, now=_NOW)
    flights = out["routes"]["CPH-AMS"]
    assert len(flights) == 2

    by_airline = {f["airline"]: f for f in flights}
    a = by_airline["KLM"]
    assert a["dep_time"] == "08:35"
    assert a["dep_date"] == "2026-08-04"
    assert a["price_cents"] == 14200  # latest price
    assert a["days_before"] == (dep - r0.date()).days
    assert len(a["history"]) == 2
    assert a["color"] is None

    b = by_airline["SAS"]
    assert b["price_cents"] == 20000
    assert len(b["history"]) == 1


def test_stale_flight_excluded():
    dep = datetime(2026, 8, 4).date()
    stale_retrieved = _NOW - timedelta(days=config.STALE_FLIGHT_DAYS + 1)
    rows = [_row(14200, retrieved=stale_retrieved, dep_date=dep)]
    out = build_flight_scatter(rows, now=_NOW)
    assert out["routes"] == {}


def test_non_stale_flight_at_boundary_included():
    dep = datetime(2026, 8, 4).date()
    boundary_retrieved = _NOW - timedelta(days=config.STALE_FLIGHT_DAYS)
    rows = [_row(14200, retrieved=boundary_retrieved, dep_date=dep)]
    out = build_flight_scatter(rows, now=_NOW)
    assert len(out["routes"]["CPH-AMS"]) == 1


def test_negative_days_before_dropped():
    dep = datetime(2026, 6, 20).date()
    r_good = datetime(2026, 6, 17, tzinfo=timezone.utc)  # 3 days before, valid
    r_bad = datetime(2026, 6, 21, tzinfo=timezone.utc)  # after departure → negative
    rows = [
        _row(15000, retrieved=r_good, dep_date=dep),
        _row(9900, retrieved=r_bad, dep_date=dep),
    ]
    out = build_flight_scatter(rows, now=_NOW)
    flight = out["routes"]["CPH-AMS"][0]
    # The negative-days_before row must not anchor the latest price...
    assert flight["price_cents"] == 15000
    assert flight["days_before"] == (dep - r_good.date()).days
    # ...nor appear in the history.
    assert len(flight["history"]) == 1
    assert all(h["days_before"] >= 0 for h in flight["history"])


def test_multi_route_two_keys():
    dep = datetime(2026, 8, 4).date()
    r0 = datetime(2026, 6, 18, tzinfo=timezone.utc)
    rows = [
        _row(14200, retrieved=r0, dep_date=dep, origin="CPH", destination="AMS"),
        _row(13000, retrieved=r0, dep_date=dep, origin="AMS", destination="CPH"),
    ]
    out = build_flight_scatter(rows, now=_NOW)
    assert set(out["routes"].keys()) == {"CPH-AMS", "AMS-CPH"}


def test_empty_input():
    assert build_flight_scatter([], now=_NOW)["routes"] == {}


def test_single_observation_flight():
    dep = datetime(2026, 8, 4).date()
    r0 = datetime(2026, 6, 18, tzinfo=timezone.utc)
    rows = [_row(14200, retrieved=r0, dep_date=dep)]
    out = build_flight_scatter(rows, now=_NOW)
    flight = out["routes"]["CPH-AMS"][0]
    assert len(flight["history"]) == 1
    assert flight["history"][0]["price_cents"] == 14200


def test_dep_dow_matches_departure_date():
    # 2026-07-14 is a Tuesday.
    dep = datetime(2026, 7, 14).date()
    r0 = datetime(2026, 6, 18, tzinfo=timezone.utc)
    rows = [_row(14200, retrieved=r0, dep_date=dep)]
    out = build_flight_scatter(rows, now=_NOW)
    assert out["routes"]["CPH-AMS"][0]["dep_dow"] == "Tue"


def test_sort_order_days_before_desc_then_price_asc():
    r0 = datetime(2026, 6, 18, tzinfo=timezone.utc)
    near = datetime(2026, 6, 25).date()  # 7 days before
    far = datetime(2026, 8, 4).date()  # 47 days before
    rows = [
        _row(14200, retrieved=r0, dep_date=near, dep_time="08:35"),
        _row(20000, retrieved=r0, dep_date=far, dep_time="09:00", airline="SAS"),
        _row(15000, retrieved=r0, dep_date=far, dep_time="19:10", airline="easyJet"),
    ]
    out = build_flight_scatter(rows, now=_NOW)
    flights = out["routes"]["CPH-AMS"]
    # furthest from departure first; within same days_before, cheaper first
    assert [f["days_before"] for f in flights] == [47, 47, 7]
    assert flights[0]["price_cents"] == 15000
    assert flights[1]["price_cents"] == 20000
