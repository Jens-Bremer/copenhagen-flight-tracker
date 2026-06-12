# Insights Data Reality Assessment

Generated from `data/flights_frontend.csv` (slim CSV exported by `scripts/build_frontend_csv.py`).

## Headline numbers

- **Total rows**: 11,379
- **Currency set**: `{EUR: 11379}` — **single currency** ✓ no normalization needed.
- **Routes**: `CPH→AMS` (5,893) and `AMS→CPH` (5,486).
- **Date span of `retrieved_at`**: 2026-05-15 → 2026-05-15 (**1 day**).
- **Unique flights** (airline + departure_date + departure_at): 4,304; **97** with only a single observation.

## Rows per airline (top)

| Airline | Rows |
|---|---|
| Scandinavian Airlines | 2,373 |
| KLM | 1,086 |
| Lufthansa | 1,070 |
| Norwegian | 752 |
| Air France | 746 |
| Air Baltic | 674 |
| Finnair | 638 |
| LOT | 550 |
| SWISS | 502 |
| British Airways | 500 |

Codeshare strings like `"KLM, Scandinavian Airlines"` (388) and `"Lufthansa, Lufthansa City Airlines"` (132) appear as distinct airlines. **Insights treat them as-is** — the contract bucket is `(route, airline_string, lead_bucket)`.

## `days_before` distribution

| Bucket | Rows |
|---|---|
| 0–6   | 356 |
| 7–13  | 477 |
| 14–20 | 81 |
| 21–29 | 1,138 |
| 30–59 | 2,073 |
| 60–89 | 1,310 |
| 90+   | 5,944 |

Buckets are spread but **far-out (90+) is heavily over-represented** — the user is tracking many future trips. Short-lead buckets (14–20) are thin.

## Bucket density `(route, airline, lead-time bucket)`

- 241 total cells.
- **≥30 obs** (dense): 92
- 3–29 obs (usable, n≥3 gate): 119
- **<3 obs** (sparse, skipped): 30

## Verdicts per Metis assumption

- **Single currency?** ✓ EUR only. Percentile/volatility/drops can use prices directly.
- **Dense enough for percentile/volatility?** ✓ For the top airlines, yes (92 cells with ≥30 obs). The n≥3 guard from the matrix convention is honored everywhere.
- **Lead-time buckets spread?** ⚠ Spread but heavily skewed to 90+. The 14–20 bucket may be statistically thin for some airlines.
- **`retrieved_at` history span?** ❌ **Only 1 day of history right now.** Implications:
  - `price_percentile` and `volatility` work — they aggregate across all observations of a `(route, airline, bucket)` regardless of when scraped.
  - `momentum` (7/14-day slope of daily-min prices) will hit the `INSIGHTS_MIN_HISTORY_DAYS` placeholder until ≥ 14 distinct `retrieved_at` days accumulate.
  - `drops` requires `DROP_MIN_PERSIST ≥ 2` consecutive scrapes — fully empty until multi-day history exists.
  - **This is expected for a fresh instance** and is exactly what Task 13's graceful-empty handling exists to cover.

## Operational note

CRLF line endings: the CSV uses LF on macOS; combined with the new `.gitattributes` (Task 4) cross-platform churn is prevented.
