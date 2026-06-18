# Insights Data Contract

Canonical formulas, JSON-blob schemas, and `config.py` keys for the four
new price-insight panels on `airlines.html`.

## Inputs

Each `build_*(rows)` function consumes the row format produced by
`src/html_generator.py:load_rows()` (already used by `build_airline_trends`
/ `build_airline_matrix`). Relevant keys:

| Key | Type | Notes |
|---|---|---|
| `retrieved_at` | `datetime` (UTC) | parsed by `load_rows`, timezone-aware |
| `departure_date` | `str` ISO date | e.g. `"2026-08-12"` |
| `departure_at` | `datetime` | parsed local airport time (used for chart x-axis only) |
| `origin`, `destination` | `str` | `CPH`, `AMS` |
| `airline` | `str` | may be a codeshare string like `"KLM, Scandinavian Airlines"` |
| `price_cents` | `int` | EUR cents per `INSIGHTS_DATA.md` |
| `price_currency` | `str` | currently always `EUR` |

Insights treat the airline string verbatim. Codeshares are not split.

## Canonical `days_before`

Cite: `src/html_generator.py:878` (in `build_airline_trends`):

```python
dep_date = date_type.fromisoformat(row["departure_date"])
days_before = (dep_date - row["retrieved_at"].date()).days
if days_before < 0:
    continue
```

All insights MUST use this exact formula. `retrieved_at` is UTC; the
date subtraction is therefore on `(departure_date_utc_naive,
retrieved_at_utc_date)` and is consistent across the codebase. Negative
`days_before` rows are dropped.

### Lead-time buckets

Single-day buckets are used (matching `build_airline_trends`). For
percentile/volatility/drops, points are grouped per
`(route, airline, days_before)` exactly as the trends builder does.

## Currency

Per `INSIGHTS_DATA.md` the dataset is single-currency (EUR). Builders
filter to the dominant currency by counting `price_currency` and
emitting a `warnings: ["mixed_currency"]` field if the dominant share
is <99%; otherwise the field is absent.

## Regeneration ritual (canonical)

```bash
python scripts/regenerate_frontend.py
```

That script (verified) chains: export DB → build slim CSV → render
`frontend/index.html` + `frontend/airlines.html` + `frontend/data.json`.

The two-step `python scripts/build_frontend_csv.py && python scripts/generate_html.py`
form also works but the wrapper is preferred.

## Output JSON-blob schemas

### `DATA_PRICE_PERCENTILE`

```jsonc
{
  "generated_at": "2026-06-12T22:00:00Z",
  "currency": "EUR",
  "min_samples": 3,
  "buckets": [
    {
      "route": "CPH-AMS",
      "airline": "KLM",
      "days_before": 14,
      "latest_price_cents": 4200,
      "reference_n": 38,
      "percentile": 18.4,
      "label": "cheap"            // cheap | typical | expensive
    }
  ]
}
```

- `percentile` is 0–100. `cheap` = ≤25, `expensive` = ≥75, else `typical`.
- Buckets with `reference_n < 3` are omitted (not rendered).
- "latest_price" = the highest-`retrieved_at` row in that bucket.

### `DATA_MOMENTUM`

```jsonc
{
  "generated_at": "2026-06-12T22:00:00Z",
  "history_days": 17,                    // distinct retrieved_at dates
  "min_history_days": 14,
  "routes": [
    {
      "route": "CPH-AMS",
      "recent_7d": {
        "direction": "falling",         // falling | flat | rising | null
        "pct_change": -8.1,             // null when insufficient
        "sample_days": 7
      },
      "recent_14d": { "direction": "flat", "pct_change": 0.4, "sample_days": 14 },
      "sweet_spot": {
        "days_before_low": 14,
        "days_before_high": 21,
        "sample_count": 42,
        "median_cents": 4400
      }
    }
  ]
}
```

- `direction` is `falling` when slope < -0.5% / day of trailing median;
  `rising` when > +0.5% / day; else `flat`. `null` if history too short.
- `sweet_spot` is derived from the existing lead-time median curve
  (min-median bucket where `sample_count ≥ 3`).

### `DATA_VOLATILITY`

```jsonc
{
  "generated_at": "2026-06-12T22:00:00Z",
  "buckets": [
    {
      "route": "CPH-AMS",
      "airline": "KLM",
      "days_before": 21,
      "n": 12,
      "std_cents": 480,
      "cv": 0.092
    }
  ]
}
```

- `cv` is unitless ratio (stdev / mean). `null` when mean=0.
- Buckets with `n < 3` omitted.
- The renderer overlays a dashed `±std` band on the existing trend chart.

### `DATA_PRICE_DROPS`

```jsonc
{
  "generated_at": "2026-06-12T22:00:00Z",
  "config": {
    "pct_threshold": 10.0,
    "reference_window_days": 30,
    "trailing_window_days": 7,
    "min_persist": 2
  },
  "history_days": 17,
  "drops": [
    {
      "route": "CPH-AMS",
      "airline": "KLM",
      "departure_date": "2026-08-12",
      "departure_at": "2026-08-12T07:25:00",
      "current_price_cents": 3200,
      "typical_price_cents": 4500,
      "pct_below": -28.9,
      "percentile": 6.3,
      "persisted_scrapes": 3
    }
  ]
}
```

- Drops are sorted by `pct_below` ascending (biggest drops first).
- Empty `drops` array is a valid output (renderer shows "no notable drops").

### `DATA_FLIGHT_SCATTER`

Per-route scatter of every currently-bookable flight at its latest observed
price, with each flight's full price history for the hover line. Powers the
"Live Flight Prices" panel (`render-flight-scatter.js`).

```jsonc
{
  "generated_at": "2026-06-18T22:00:00Z",
  "routes": {
    "CPH-AMS": [
      {
        "airline": "KLM",            // string, verbatim (codeshares not split)
        "dep_time": "08:35",         // HH:MM 24-hr, departure-airport local time
        "dep_date": "2026-08-04",    // ISO date of departure
        "dep_dow": "Mon",            // 3-letter day-of-week of dep_date
        "days_before": 47,           // int, at the latest observation
        "price_cents": 14200,        // int, latest observed price (EUR cents)
        "color": null,               // always null; JS resolves via airlineColor()
        "history": [                 // chronological, oldest → newest
          { "days_before": 61, "price_cents": 15800 },
          { "days_before": 54, "price_cents": 15200 },
          { "days_before": 47, "price_cents": 14200 }
        ]
      }
    ],
    "AMS-CPH": [ ... ]
  }
}
```

- Flight identity = `(route, departure_date, airline, dep_time)`. Only the
  latest observation (highest `retrieved_at`) supplies the scatter point;
  every observation supplies one `history` entry.
- `days_before` uses the canonical formula `(departure_at.date() -
  retrieved_at.date()).days`. Observations with `days_before < 0` are dropped
  before the latest-price and history computation.
- **Staleness exclusion:** a flight is excluded entirely when its latest
  observation is older than `config.STALE_FLIGHT_DAYS` days before `now`
  (`(now.date() - latest_retrieved_at.date()).days > STALE_FLIGHT_DAYS`). A
  flight last seen exactly `STALE_FLIGHT_DAYS` days ago is still included.
- `color` is always `null`; the renderer resolves the airline colour via
  `airlineColor()` at render time.
- Within each route, flights are sorted by `days_before` descending (furthest
  from departure first), then `price_cents` ascending as tiebreaker.
- Single-observation flights are valid (history has one entry; the renderer
  draws no line for them). No minimum-observation gate and no
  `insufficient_data` marker — the chart is renderable whenever any non-stale
  rows exist, and emits `{"routes": {}}` otherwise.

## `config.py` keys (added)

| Key | Default | Used by |
|---|---|---|
| `INSIGHTS_MIN_HISTORY_DAYS` | `14` | all 4 builders (graceful empty) |
| `DROP_PCT_THRESHOLD` | `10.0` | `build_price_drops` |
| `DROP_REFERENCE_WINDOW_DAYS` | `30` | `build_price_drops` |
| `DROP_TRAILING_WINDOW_DAYS` | `7` | `build_price_drops` |
| `DROP_MIN_PERSIST` | `2` | `build_price_drops` |
| `BROWSER_PROFILE_MAX_BYTES` | `300_000_000` | `scripts/cleanup_profiles.py` |

All have safe defaults so missing config does not break the build.

## Empty / sparse-data marker

When a builder cannot produce useful output it returns the shape with
an `insufficient_data` field, e.g.

```jsonc
{ "generated_at": "...", "insufficient_data": "need_min_14_days_history", "drops": [] }
```

Renderers branch on this field to show the friendly placeholder.
