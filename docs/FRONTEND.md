# Frontend — Architecture, Data Contract & Integration Guide

> This document is the single source of truth for the static dashboard at
> `frontend/index.html`. It explains how the page is generated, what data
> contract it expects from the backend, where every visual rule lives, and
> how to extend it without breaking the pipeline.

**Audience:** developers wiring backend changes (new fields, new airlines,
new analytics) to the existing static dashboard.

---

## TL;DR

- The browser **does not fetch data.** The dashboard is a single static
  HTML file with **five JSON blobs inlined at build time** by
  `scripts/generate_html.py` (which delegates to `src/html_generator.py`).
- The build runs **nightly at 23:46** inside the scheduler, chained from
  the frontend-CSV job (`scripts/build_frontend_csv.py`). No separate cron
  entry — a slow CSV build can never race past the clock.
- The frontend is **plain HTML + CSS + JS** (no bundler, no transpilation,
  no Node toolchain). The only third-party JS is **Chart.js 4.4.3**,
  vendored under `frontend/vendor/chart.min.js` and **inlined** into the
  output. The page works fully offline; only DM Sans / DM Serif Display
  fonts are fetched from Google Fonts.
- To wire a backend change end-to-end you almost always touch
  `src/frontend_csv_builder.py` **and** the matching `build_*()` function
  in `src/html_generator.py`. The browser code only changes when the
  shapes of the five JSON blobs change.

---

## Build pipeline — who emits what

```
              ┌──────────────────────────┐
              │  flight_observations DB  │   data/flights.db
              └────────────┬─────────────┘
                           │  scripts/build_frontend_csv.py
                           ▼
              ┌──────────────────────────┐
              │ data/flights_frontend.csv│   slim, typed, sorted
              └────────────┬─────────────┘
                           │  scripts/generate_html.py
                           │   → src/html_generator.generate()
                           ▼
                ┌─────────────────────┐
                │ frontend/           │
                │  index.html         │  ← written nightly
                │  (5 JSON blobs +    │
                │   inlined styles,   │
                │   app.js, chart.js) │
                └─────────────────────┘
```

| File | Owner | When it runs |
| --- | --- | --- |
| `scripts/run_scheduler.py` | daemon | always |
| `scripts/build_frontend_csv.py` | nightly job @ 23:46 | writes `data/flights_frontend.csv` |
| `scripts/generate_html.py` | **inline tail** of the 23:46 job | reads CSV → writes `frontend/index.html` |
| `src/html_generator.py` | library | five `build_*()` functions + a renderer |
| `frontend/index.html.template` | template | `${PLACEHOLDER}` strings filled by the renderer |
| `frontend/styles.css` | static asset | inlined into the output |
| `frontend/app.js` | static asset | inlined into the output |
| `frontend/vendor/chart.min.js` | static asset (vendored) | inlined into the output |
| `frontend/index.html` | **output** | regenerated, **do not edit by hand** |

> **Never edit `frontend/index.html` directly** — the file is overwritten
> by the next 23:46 run. Edit `index.html.template`, `styles.css`, or
> `app.js` instead, then run `python scripts/generate_html.py` to rebuild.

---

## The data contract — five JSON blobs

The dashboard is data-driven. Every visual reads from one of five JSON
blobs embedded in the page as
`<script type="application/json" id="DATA_*">…</script>` nodes. The
**shapes of these five blobs ARE the API**. Any backend change that adds,
removes, or renames a field touches both ends of this contract.

The blobs are produced by `src/html_generator.py`:

| Blob ID | Built by | Used by `app.js` |
| --- | --- | --- |
| `DATA_METADATA` | `build_metadata(rows, generated_at)` | `renderHeader`, `wireFilters` |
| `DATA_CALENDAR` | `build_calendar(rows)` | `renderCalendar` |
| `DATA_FLIGHTS` | `build_flights(rows)` | `renderDrilldown`, `drawPriceHistory` |
| `DATA_ANALYSIS` | `build_analysis(rows)` | `renderTrends`, `renderFooterCharts` |
| `DATA_SUMMARY` | `build_summary(rows)` | `renderHistograms`, `renderWeekendPairs` |

### 1. `DATA_METADATA`

```json
{
  "generated_at": "2026-05-15T23:47Z",
  "date_range": { "from": "2026-05-15", "to": "2026-08-13" },
  "total_rows": 14882,
  "routes": ["AMS-CPH", "CPH-AMS"],
  "airlines": ["KLM", "Norwegian", "SAS", "easyJet"]
}
```

- `generated_at` — UTC, minute resolution, `Z` suffix. The canonical
  timestamp format for the whole project.
- `date_range.from` / `to` — earliest / latest **departure** date in the
  CSV (ISO `YYYY-MM-DD`). Drives the calendar grid bounds.
- `total_rows` — used only as an "are we empty?" sentinel. `0` triggers
  the "No flight observations available" fallback.
- `routes` — the union of `${origin}-${destination}` keys present in the
  data. The route toggle always shows the three fixed buttons
  (`CPH-AMS`, `AMS-CPH`, `Both`) regardless of this field.
- `airlines` — the union of distinct `airline` values present. Drives the
  airline-filter chips (one chip per name, sorted alphabetically).

### 2. `DATA_CALENDAR`

Per (route, departure date), the cheapest observed price + distinct
flight count.

```json
{
  "CPH-AMS": {
    "2026-05-15": { "min_cents": 4250, "flight_count": 4 },
    "2026-05-16": { "min_cents": 5100, "flight_count": 3 }
  },
  "AMS-CPH": { ... }
}
```

- Two top-level keys, always: `CPH-AMS` and `AMS-CPH`.
- Each inner key is an ISO date string (`YYYY-MM-DD`).
- `min_cents` — integer cents (so `€42.50` is `4250`). Cents-not-euros
  everywhere; never floats.
- `flight_count` — distinct `(airline, departure_time)` tuples seen on
  that date for that route.

### 3. `DATA_FLIGHTS`

Per (route, departure date), the full list of flights with price history.

```json
{
  "CPH-AMS": {
    "2026-05-15": [
      {
        "airline": "KLM",
        "dep_time": "07:25",
        "arr_time": "09:00",
        "duration_minutes": 95,
        "overnight": false,
        "latest_cents": 4250,
        "history": [
          { "obs_date": "2026-04-10", "price_cents": 5100, "days_before": 35 },
          { "obs_date": "2026-04-25", "price_cents": 4250, "days_before": 20 }
        ]
      }
    ]
  },
  "AMS-CPH": { ... }
}
```

Flight identity = `(airline, dep_time)`. Multiple scrape snapshots of the
same flight collapse into one entry with the snapshots in `history`.

- `dep_time` / `arr_time` — `HH:MM` strings in **departure-airport local
  time** (not UTC). The page never timezone-converts.
- `overnight` — `true` when `arrival_at.date > departure_at.date`.
  Drives the `+1` pill on the flight row.
- `latest_cents` — the most recent observation's price.
- `history` — chronologically sorted by `obs_date`.
- `days_before` — `departure_date - obs_date`, in days. Always ≥ 0 (the
  builder filters defensively in case of clock skew).
- Within each date, flights are sorted by `(latest_cents, dep_time)` —
  cheapest first.

### 4. `DATA_ANALYSIS`

Per route, the derived stats.

```json
{
  "CPH-AMS": {
    "lead_time_curve": [
      { "days_before": 0, "mean_cents": 8800, "min_cents": 5400, "obs_count": 12 },
      { "days_before": 1, "mean_cents": 8100, "min_cents": 5200, "obs_count": 15 }
    ],
    "sweet_spot_days": 38,
    "day_of_week": [
      { "dow": 0, "label": "Mon", "mean_cents": 5100 },
      { "dow": 1, "label": "Tue", "mean_cents": 4800 }
    ],
    "month": [
      { "month": 6, "label": "Jun", "mean_cents": 4900 },
      { "month": 7, "label": "Jul", "mean_cents": 6300 }
    ],
    "market_trend": [
      { "obs_date": "2026-04-10", "min_cents": 4250 },
      { "obs_date": "2026-04-11", "min_cents": 4180 }
    ]
  },
  "AMS-CPH": { ... }
}
```

- `lead_time_curve` — mean / min / count per `days_before` bucket. The
  lead-time chart plots `days_before` (x, reversed) vs `mean_cents / 100`
  (y).
- `sweet_spot_days` — the `days_before` value where `mean_cents` is
  smallest. Surfaced as the headline beneath the trends panel; we are
  intentionally descriptive, not predictive (note the chart's subtitle).
- `day_of_week.dow` — `0 = Monday` … `6 = Sunday`. The mean here is
  computed from the **cheapest-per-departure-date** distribution, *not*
  raw observations, so booking density doesn't skew the answer.
- `month.month` — `1 = Jan` … `12 = Dec`. Same per-departure aggregation
  as `day_of_week`.
- `market_trend` — one entry per observation date, value = cheapest
  observed price that day. Drives the "market trend" chart on the left
  of the trends panel.

### 5. `DATA_SUMMARY`

Per route, the histogram + weekend pairs.

```json
{
  "CPH-AMS": {
    "histogram": {
      "KLM": [
        { "bin_low": 4000, "bin_high": 4500, "count": 12 },
        { "bin_low": 4500, "bin_high": 5000, "count": 7 }
      ],
      "Ryanair": [ ... ]
    },
    "weekend_pairs": [
      {
        "fri_date": "2026-06-06",
        "fri_airline": "KLM", "fri_dep": "07:25", "fri_cents": 4250,
        "sun_date": "2026-06-08",
        "sun_airline": "easyJet", "sun_dep": "18:10", "sun_cents": 4800,
        "total_cents": 9050
      }
    ]
  },
  "AMS-CPH": { "histogram": { ... }, "weekend_pairs": [] }
}
```

- `histogram` — €5 bins (`BIN_WIDTH_CENTS = 500` in
  `src/html_generator.py`). One series per airline; bars are coloured by
  the locked airline palette in `frontend/app.js`. SAS / Scandinavian
  Airlines is `#FFFFFF` and gets a brown outline so it stays visible.
- `weekend_pairs` — meaningful only on `CPH-AMS` in the current build
  (Friday CPH→AMS + Sunday AMS→CPH joined by total cost, top 5 cheapest).
  `AMS-CPH.weekend_pairs` is always an empty array — kept in the output
  for shape symmetry. Update both `WEEKEND_PAIRS_TOP_N` and the
  `weekday() != 4` check in `build_summary` if you ever generalise this.

---

## DOM contract — IDs the JS expects

`app.js` asserts the presence of these IDs at boot and refuses to render
if any are missing (see `REQUIRED_DOM_IDS` and `assertRequiredDomIds`).
The template **must** keep them. If you add a panel, add its IDs here and
to the assertion list.

| ID | Purpose |
| --- | --- |
| `header-range` | "Data: from → to" line in the header. |
| `header-generated` | "Generated …Z" line in the header. |
| `footer-generated` | Same timestamp echoed in the footer. |
| `route-toggle` | Container for the route filter chips. |
| `airline-filter` | Container for the airline filter chips. |
| `calendar` | The 7-column grid. Rebuilt entirely on every render. |
| `drilldown-panel` | The panel section (scroll target on date select). |
| `drilldown-title` | The `<span>` inside the heading. |
| `drilldown` | Container for the flight rows. |
| `price-history-wrap` | The chart container — hidden until a flight is selected. |
| `price-history-chart` | The Chart.js canvas. |
| `market-trend-chart`, `leadtime-chart` | Trends-panel canvases. |
| `sweet-spot-headline` | Paragraph beneath the trends panel. |
| `histogram-out`, `histogram-back` | Histogram canvases (CPH-AMS / AMS-CPH). |
| `weekend-pairs` | Container that the JS fills with `<table>` markup. |
| `dow-chart`, `month-chart` | Cheapness-overview canvases. |

JSON blob node IDs (read by `readJsonBlob`):
`DATA_METADATA`, `DATA_CALENDAR`, `DATA_FLIGHTS`, `DATA_ANALYSIS`,
`DATA_SUMMARY`.

---

## When to use each panel

| If you want to answer… | …look at this panel |
| --- | --- |
| "How does the next 90 days look?" | Calendar — green = cheap, red = expensive, today is dashed. |
| "What's flying on this specific date?" | Click a date → drill-down flight list. |
| "Should I book now or wait?" | Trends → lead-time chart + sweet-spot headline. |
| "Is the market trending up or down?" | Trends → market-trend chart. |
| "Which airline competes on price?" | Histograms — €5 bins coloured per airline. |
| "What's the cheapest weekend break?" | Weekend pairs table. |
| "Which day-of-week / month is cheapest in general?" | Cheapness overview (the green bar is the minimum). |

The filters bar is sticky on desktop so the route toggle and airline
chips stay reachable while drilling.

---

## How to extend safely

### Add a new airline

1. The scraper will already pick it up — no schema change. Verify:
   `python scripts/query_prices.py --stats` should show the new airline
   in the airline list.
2. Add its brand colour to `AIRLINE_COLORS` in `frontend/app.js`.
   - If the colour is white or near-white, add the airline name to the
     `AIRLINE_OUTLINE` set so it gets a `1.5px` brown outline.
3. Run `python scripts/generate_html.py` to regenerate.

The page handles unknown airlines gracefully — they fall through to a
deterministic warm-arc HSL based on a hash of the airline name. But the
moment you know the brand colour, lock it in.

### Add a new field to a flight row

1. Add the column to `data/flights.db` as **NULLABLE** (never break
   historical data — see `CLAUDE.md`'s "Rule for Updates").
2. Read it in `src/frontend_csv_builder.py`, write it through to
   `data/flights_frontend.csv`.
3. Pick it up in `src/html_generator.py:load_rows` and either
   `build_flights` (per-row) or `build_summary` (aggregated).
4. Render it in `frontend/app.js:renderDrilldown` — add a `<span>` to
   the row template. Update the grid-template-columns if needed.
5. Document the new field in this file's **The data contract** section.

### Add a new panel

1. Add the panel `<section>` to `frontend/index.html.template`, with a
   `panel__heading` (the flag prefix is automatic) and any canvas /
   container nodes.
2. Add every container ID to `REQUIRED_DOM_IDS` in `app.js`.
3. If the panel needs a new JSON blob, add a `build_X(rows)` function in
   `src/html_generator.py` and embed it in `render_html()` and the
   template (`<script type="application/json" id="DATA_X">${DATA_X}</script>`).
4. Add a `renderX()` function in `app.js`, register charts with
   `destroyChart` (mandatory — Chart.js leaks otherwise), and call it
   from `renderAll()`.
5. Re-run `python scripts/generate_html.py`.

### Add a new chart to an existing panel

You only need to touch `app.js`:

1. Add the canvas to the template.
2. Add a slot to the `charts` registry (`charts.myNewChart = null`).
3. Register the new ID in `REQUIRED_DOM_IDS`.
4. Always call `destroyChart('myNewChart')` before creating a fresh one.
5. Always reference colours via CSS custom properties
   (`var(--color-orange)` etc) so re-theming flows.

### Re-theme

All colour/spacing/type tokens live in **two files** that act as one:

- `frontend/styles.css` (top-of-file `:root` block) — what the browser sees.
- `colors_and_type.css` in the design system — the canonical token list
  with comments and aliases.

If you change a token in one, change it in both. Airline colours are
mirrored in `app.js`'s `AIRLINE_COLORS` map — keep that in sync too.

---

## Local development

The dashboard is a **static file**. You don't need the Python pipeline
running to develop the frontend.

### Iterate on CSS / JS

```bash
# 1. Build a fresh index.html from existing CSV
python scripts/generate_html.py

# 2. Open it
open frontend/index.html        # macOS
xdg-open frontend/index.html    # Linux
```

After editing `styles.css` or `app.js`, **re-run `generate_html.py`** —
the changes are inlined at build time, not loaded by reference.

### Iterate without backend data

1. Save a known-good `frontend/index.html` from a recent build.
2. Open it in your editor and find the five
   `<script type="application/json" id="DATA_*">…</script>` nodes.
3. Edit the JSON directly to mock the scenarios you want to test (empty
   day, single-airline filter, calendar gap, etc.).
4. Refresh the page in the browser.

For a more disciplined approach, see the UI-kit demo in the design
system project (`ui_kits/website/data.js`) — it builds the five blobs
deterministically from a seeded PRNG and can be lifted into a dev
fixture if needed.

### Debug hooks

`app.js` exposes the live state and data on `window.__tracker`:

```js
window.__tracker.state      // { route, selectedDate, selectedFlight, airlineFilter }
window.__tracker.DATA       // { metadata, calendar, flights, analysis, summary }
```

Read-only in spirit — mutating either bypasses `renderAll` and the page
will drift out of sync.

---

## Design tokens (cheat sheet)

All in `:root` at the top of `frontend/styles.css`.

- **Paper / ink** — `--color-cream`, `--color-cream-mid`,
  `--color-cream-dark`, `--color-text`, `--color-brown`,
  `--color-brown-light`.
- **The tricolour (price scale)** — `--color-green-ahead` →
  `--color-yellow` → `--color-orange` → `--color-red`. Cheap is green;
  expensive is red.
- **Airline colours** — `--airline-klm`, `--airline-norwegian`,
  `--airline-easyjet`, `--airline-sas`, `--airline-ryanair`,
  `--airline-finnair`. Locked.
- **Type** — `--font-display: 'DM Serif Display'`,
  `--font-body: 'DM Sans'`.
- **Spacing** — 4 / 8 / 16 / 24 / 40 / 64 px on a strict ramp.
- **Radii** — `4px` everywhere; `999px` only on filter chips; calendar
  cells `3px`.
- **One border** — `1.5px solid var(--color-brown)`.

---

## Brand rules (the short list)

1. **The three-stripe ribbon is the brand mark.** Red / orange / yellow,
   in that order. It appears full-width under the header, miniaturised
   as a prefix on every panel heading, and as the basis of the price
   scale. Never replace it with a logo, never re-colour it.
2. **No icons.** No icon font, no inline SVG glyphs, no emoji, no
   unicode-character icons. The vocabulary is type + stripe +
   airline-colour swatch.
3. **No imagery.** The product is paper, ink, and texture. If imagery is
   ever introduced, warm-tint it and frame it with the ribbon.
4. **Tabular numerals on every price and time.** Non-negotiable.
5. **Voice is terse, technical, self-deprecating.** Hedge data claims
   inline ("descriptive history; not a prediction"). Lowercase
   parenthetical asides are part of the register, not a typo to fix.

---

## File map (quick reference)

```
config.py                          tuneable thresholds, routes, paths
scripts/
  run_scheduler.py                 the daemon — runs continuously
  build_frontend_csv.py            emits data/flights_frontend.csv @23:46
  generate_html.py                 emits frontend/index.html (chained tail)
  fetch_vendor.py                  one-time Chart.js download
src/
  frontend_csv_builder.py          DB → slim CSV
  html_generator.py                CSV → JSON blobs → HTML  ← THE renderer
frontend/
  index.html.template              skeleton with ${PLACEHOLDER}s
  styles.css                       all CSS, inlined at build time
  app.js                           all JS, inlined at build time
  vendor/chart.min.js              Chart.js 4.4.3, inlined at build time
  index.html                       GENERATED — do not edit by hand
docs/
  FRONTEND.md                      ← you are here
```

---

## Caveats & known limitations

- The dashboard is **descriptive, not predictive.** Trends + sweet-spot
  numbers summarise observed history; they are not a recommendation
  engine. The chart titles say so explicitly.
- Layovers and round trips are **not modelled.** If you add them, follow
  the "add a new field" recipe and keep historical rows parsing
  (`NULLABLE` columns, no renames).
- The page is **single-locale** (`en-GB` date formatting) and **single
  timezone** (departure-airport local time, UTC for `generated_at`). The
  CLAUDE.md notes flag this as untested.
- Chart.js is **inlined**. The output HTML is ~250 KB. That's the cost
  of working fully offline.
