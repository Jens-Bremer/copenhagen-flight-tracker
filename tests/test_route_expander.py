from datetime import date

from src.route_expander import expand_jobs


ROUTES = [("CPH", "AMS"), ("AMS", "CPH")]
DATES = [date(2025, 9, 5), date(2025, 9, 6), date(2025, 9, 7)]


def test_output_length_is_routes_times_dates():
    jobs = expand_jobs(ROUTES, DATES)
    assert len(jobs) == len(ROUTES) * len(DATES)


def test_all_routes_appear():
    jobs = expand_jobs(ROUTES, DATES)
    found_routes = {(origin, dest) for origin, dest, _ in jobs}
    assert found_routes == set(ROUTES)


def test_all_dates_appear():
    jobs = expand_jobs(ROUTES, DATES)
    found_dates = {d for _, _, d in jobs}
    assert found_dates == set(DATES)


def test_each_combination_appears_exactly_once():
    jobs = expand_jobs(ROUTES, DATES)
    assert len(set(jobs)) == len(ROUTES) * len(DATES)


def test_order_is_deterministic_for_same_day():
    jobs_a = expand_jobs(ROUTES, DATES)
    jobs_b = expand_jobs(ROUTES, DATES)
    assert jobs_a == jobs_b


def test_order_differs_across_days():
    jobs_day1 = expand_jobs(ROUTES, DATES, seed=date(2025, 9, 1).toordinal())
    jobs_day2 = expand_jobs(ROUTES, DATES, seed=date(2025, 9, 2).toordinal())
    # With 6 items, different seeds should almost always produce different orders.
    assert jobs_day1 != jobs_day2


def test_not_grouped_by_route():
    # With enough dates, same-route items should not all be contiguous.
    dates = [date(2025, 9, 5 + i) for i in range(10)]
    jobs = expand_jobs(ROUTES, dates, seed=42)
    routes_seq = [(o, d) for o, d, _ in jobs]
    # If every first-half item had the same route, they'd be grouped.
    first_route = routes_seq[0]
    assert not all(r == first_route for r in routes_seq[: len(dates)])
