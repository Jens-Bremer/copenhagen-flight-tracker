/**
 * Copenhagen Flight Tracker — frontend renderer.
 *
 * The browser does not fetch data. Five JSON blobs are embedded in the
 * HTML by src/html_generator.py at build time:
 *   DATA_METADATA, DATA_CALENDAR, DATA_FLIGHTS, DATA_ANALYSIS, DATA_SUMMARY
 *
 * This file reads them on boot, manages a tiny `state` object, and
 * re-renders panels in response to filter / selection changes. Charts
 * are drawn with Chart.js 4.4.3 (inlined into the page above this script).
 *
 * UX refinements in this revision (no JSON-shape changes — backend is
 * untouched). Search for "CHANGE (UX)" to see every modification:
 *   1. Filter groups labelled "Route" / "Airline".
 *   2. Calendar emits month-divider rows + min/max legend + per-cell
 *      cheapest-airline dot + a dashed "today" outline.
 *   3. Drill-down panel heading shows the selected date inline.
 */
(function () {
  'use strict';

  // ───── Airline brand colours (locked) ──────────────────────────────────────
  const AIRLINE_COLORS = {
    'KLM':                    '#00A1DE',
    'Norwegian':              '#D4001E',
    'easyJet':                '#FF6600',
    'Scandinavian Airlines':  '#FFFFFF',
    'SAS':                    '#FFFFFF',
    'Ryanair':                '#F1C40F',
    'Finnair':                '#00386F',
  };
  const AIRLINE_OUTLINE = new Set(['Scandinavian Airlines', 'SAS']);

  // ───── State (single source of truth) ──────────────────────────────────────
  const state = {
    route: 'CPH-AMS',        // 'CPH-AMS' | 'AMS-CPH' | 'both'
    calendarMonth: null,     // 'YYYY-MM' — currently displayed month
    selectedDate: null,      // 'YYYY-MM-DD' | null
    selectedFlight: null,    // { airline, dep_time } | null
    airlineFilter: new Set(), // empty Set = all airlines visible
    drilldownSort: 'price',  // 'price' | 'time'
  };

  // ───── Data (populated once on boot) ───────────────────────────────────────
  let DATA = null;

  // ───── Chart registry — destroy before re-render to avoid leaks ────────────
  const charts = {
    priceHistory: null,
    marketTrend: null,
    leadtime: null,
    histogramOut: null,
    histogramBack: null,
    dow: null,
    month: null,
    timeheatOut: null,
    timeheatBack: null,
    normProg: null,
  };
  function destroyChart(slot) {
    if (charts[slot]) { charts[slot].destroy(); charts[slot] = null; }
  }

  /** Build a visually-hidden table next to a chart canvas so screen readers
   *  can read the underlying data. `rows` is an array of objects whose keys
   *  become column headers. */
  function chartA11ySummary(parentCanvas, rows) {
    const wrap = parentCanvas.parentElement;
    if (!wrap) return;
    let table = wrap.querySelector('.visually-hidden');
    if (!table) {
      table = document.createElement('div');
      table.className = 'visually-hidden';
      wrap.appendChild(table);
    }
    if (!rows.length) { table.innerHTML = ''; return; }
    table.innerHTML = `<table><thead><tr>${
      Object.keys(rows[0]).map((k) => `<th>${escapeHtml(k)}</th>`).join('')
    }</tr></thead><tbody>${
      rows.map((r) => '<tr>' + Object.values(r).map((v) => `<td>${escapeHtml(v)}</td>`).join('') + '</tr>').join('')
    }</tbody></table>`;
  }

  // ───── Tiny helpers ────────────────────────────────────────────────────────
  function $(id) { return document.getElementById(id); }
  function formatPrice(cents) { return '€' + Math.round(cents / 100); }

  /** HTML-escape *s* for safe interpolation into `innerHTML`. Defends against
   *  attacker-controlled airline names from the upstream scraper. */
  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function formatDate(iso) {
    const [y, m, d] = iso.split('-').map(Number);
    return new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
      .format(new Date(y, m - 1, d));
  }

  function formatMonth(date) {
    return new Intl.DateTimeFormat('en-GB', { month: 'long', year: 'numeric' }).format(date);
  }

  function todayIso() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  }

  const REQUIRED_DOM_IDS = [
    'header-range', 'header-generated', 'footer-generated',
    'route-toggle', 'airline-filter',
    'hero-best-time', 'hero-market', 'hero-book-when',
    'cal-prev', 'cal-month-label', 'cal-next',
    'calendar', 'drilldown-panel', 'drilldown-title', 'drilldown-sort', 'drilldown',
    'price-history-wrap', 'verdict-card', 'price-history-chart',
    'market-trend-chart', 'leadtime-chart', 'sweet-spot-headline',
    'histogram-out', 'histogram-back',
    'weekend-pairs',
    'dow-chart', 'month-chart',
    'timeheat-out', 'timeheat-back',
    'normprog-chart',
  ];
  function assertRequiredDomIds() {
    const missing = REQUIRED_DOM_IDS.filter((id) => !$(id));
    if (missing.length) throw new Error('Missing DOM IDs: ' + missing.join(', '));
  }
  function fatalBanner(msg) {
    const banner = document.createElement('div');
    banner.className = 'error-banner';
    banner.role = 'alert';
    banner.textContent = msg;
    document.body.insertBefore(banner, document.body.firstChild);
  }

  /** Deterministic warm-arc hue (0–60° ∪ 350–360°) for unknown airlines. */
  function airlineColor(airline) {
    if (AIRLINE_COLORS[airline]) return AIRLINE_COLORS[airline];
    let h = 0;
    for (let i = 0; i < airline.length; i++) h = (h * 31 + airline.charCodeAt(i)) >>> 0;
    const arc = h % 70;                                       // 0-69
    const hue = arc < 60 ? arc : 350 + (arc - 60);            // 0–59 or 350–359
    return `hsl(${hue}, 70%, 50%)`;
  }

  // ───── Data loading ────────────────────────────────────────────────────────
  function readJsonBlob(id) {
    const el = $(id);
    if (!el) return null;
    try { return JSON.parse(el.textContent); }
    catch (e) { console.error('Failed to parse', id, e); return null; }
  }

  function loadData() {
    return {
      metadata: readJsonBlob('DATA_METADATA') || {},
      calendar: readJsonBlob('DATA_CALENDAR') || {},
      flights: readJsonBlob('DATA_FLIGHTS') || {},
      analysis: readJsonBlob('DATA_ANALYSIS') || {},
      summary: readJsonBlob('DATA_SUMMARY') || {},
    };
  }

  // ───── Panel renderers ────────────────────────────────────────────────────
  function renderHeader() {
    if (!DATA.metadata) return;
    const range = DATA.metadata.date_range || {};
    if (range.from && range.to) {
      $('header-range').textContent = `Data: ${formatDate(range.from)} → ${formatDate(range.to)}`;
    }
    if (DATA.metadata.generated_at) {
      $('header-generated').textContent = `Generated ${DATA.metadata.generated_at}`;
      $('footer-generated').textContent = DATA.metadata.generated_at;
    }
  }

  /** Returns { min, max } across all cells the user is currently allowed to see. */
  function calendarPriceRange() {
    let min = Infinity, max = -Infinity;
    activeRoutes().forEach((route) => {
      const cells = DATA.calendar[route] || {};
      for (const date in cells) {
        const v = cells[date].min_cents;
        if (v < min) min = v;
        if (v > max) max = v;
      }
    });
    if (!isFinite(min)) return null;
    return { min, max };
  }

  /** Linear green→amber→red interpolation across [min, max], returned as CSS rgb. */
  function priceTint(cents, range) {
    if (!range || range.max === range.min) return 'rgba(241, 196, 15, 0.35)';
    const t = (cents - range.min) / (range.max - range.min);     // 0 = cheap, 1 = expensive
    // 0=#3d7a3d green, 0.5=#e67e22 orange, 1=#c0392b red
    const lerp = (a, b, k) => Math.round(a + (b - a) * k);
    let r, g, b;
    if (t < 0.5) {
      const k = t * 2;
      r = lerp(61, 230, k); g = lerp(122, 126, k); b = lerp(61, 34, k);
    } else {
      const k = (t - 0.5) * 2;
      r = lerp(230, 192, k); g = lerp(126, 57, k); b = lerp(34, 43, k);
    }
    return `rgba(${r}, ${g}, ${b}, 0.32)`;
  }

  /** CHANGE (UX): Cheapest airline brand-colour visible on a given date,
   *  across the currently active routes + airline filter. Returns null if
   *  no flight is visible (the cell renders without a dot). */
  function cheapestAirlineColor(iso) {
    let bestAirline = null, bestPrice = Infinity;
    activeRoutes().forEach((route) => {
      const list = ((DATA.flights[route] || {})[iso]) || [];
      list.forEach((f) => {
        if (!airlinePasses(f.airline)) return;
        if (f.latest_cents < bestPrice) {
          bestPrice = f.latest_cents; bestAirline = f.airline;
        }
      });
    });
    return bestAirline ? airlineColor(bestAirline) : null;
  }

  /** Sorted list of 'YYYY-MM' strings covering the full data date range. */
  function availableMonths() {
    const dr = DATA.metadata.date_range || {};
    if (!dr.from || !dr.to) return [];
    const months = [];
    let [y, m] = dr.from.split('-').map(Number);
    const [ty, tm] = dr.to.split('-').map(Number);
    while (y < ty || (y === ty && m <= tm)) {
      months.push(`${y}-${String(m).padStart(2, '0')}`);
      m++;
      if (m > 12) { m = 1; y++; }
    }
    return months;
  }

  function renderCalendar() {
    const root = $('calendar');
    root.innerHTML = '';
    root.className = 'calendar';
    const oldLegend = root.parentElement && root.parentElement.querySelector('.calendar-legend');
    if (oldLegend) oldLegend.remove();

    // Guard: calendarMonth must be set before rendering.
    if (!state.calendarMonth) return;

    const range = calendarPriceRange();
    if (!range) {
      root.outerHTML = `<div id="calendar" class="empty-state">No flights match the current filters.</div>`;
      return;
    }

    // Update nav label and button states.
    const months = availableMonths();
    const monthIdx = months.indexOf(state.calendarMonth);
    const [cy, cm] = state.calendarMonth.split('-').map(Number);
    const labelEl = $('cal-month-label');
    if (labelEl) labelEl.textContent = formatMonth(new Date(cy, cm - 1, 1));
    const prevBtn = $('cal-prev'), nextBtn = $('cal-next');
    if (prevBtn) prevBtn.disabled = (monthIdx <= 0);
    if (nextBtn) nextBtn.disabled = (monthIdx >= months.length - 1);

    // Weekday header row.
    ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].forEach((w) => {
      const el = document.createElement('div');
      el.className = 'calendar__weekday';
      el.textContent = w;
      root.appendChild(el);
    });

    // Grid for this month only. Pad start to Monday, complete last week to Sunday.
    let cursor = new Date(cy, cm - 1, 1);
    const end = new Date(cy, cm, 0);                              // last day of month
    const padDays = (cursor.getDay() + 6) % 7;                   // 0=Mon…6=Sun
    cursor.setDate(cursor.getDate() - padDays);

    function cellPrice(iso) {
      let cheapest = Infinity;
      activeRoutes().forEach((route) => {
        const v = (DATA.calendar[route] || {})[iso];
        if (v && v.min_cents < cheapest) cheapest = v.min_cents;
      });
      return isFinite(cheapest) ? cheapest : null;
    }

    const todayStr = todayIso();

    while (cursor <= end || ((cursor.getDay() + 6) % 7) !== 0) {
      // Use local date components — toISOString() converts to UTC and shifts
      // dates in timezones east of UTC (e.g. CEST: local midnight → prev UTC day).
      const iso = `${cursor.getFullYear()}-${String(cursor.getMonth() + 1).padStart(2, '0')}-${String(cursor.getDate()).padStart(2, '0')}`;

      const cell = document.createElement('div');
      const price = cellPrice(iso);
      cell.className = 'calendar__cell' + (price === null ? ' is-empty' : '');
      if (iso === todayStr && price !== null) cell.classList.add('is-today');
      cell.dataset.date = iso;
      // Cheapest flight's trajectory from DATA.flights (first entry = cheapest by sort order).
      let cellTrajectory = null;
      if (price !== null) {
        activeRoutes().forEach((route) => {
          const list = ((DATA.flights[route] || {})[iso]) || [];
          if (list.length && !cellTrajectory) cellTrajectory = list[0].trajectory;
        });
      }
      const trajectoryGlyph = cellTrajectory === 'down'   ? '↓'
                             : cellTrajectory === 'up'    ? '↑'
                             : cellTrajectory === 'stable' ? '→' : '';
      const trajectoryAriaLabel = cellTrajectory === 'down'
        ? 'Prices trending down'
        : cellTrajectory === 'up' ? 'Prices trending up' : 'Prices stable';
      const trajectoryHtmlStr = trajectoryGlyph
        ? `<span class="calendar__cell__trajectory calendar__cell__trajectory--${cellTrajectory}"
               aria-label="${trajectoryAriaLabel}">${trajectoryGlyph}</span>`
        : '';
      cell.innerHTML = `
        <span class="calendar__cell__day">${cursor.getDate()}</span>
        <span class="calendar__cell__price">${price !== null ? formatPrice(price) : '—'}</span>
        ${trajectoryHtmlStr}
      `;
      if (price !== null) {
        cell.style.background = priceTint(price, range);
        cell.tabIndex = 0;
        cell.setAttribute('role', 'button');
        cell.setAttribute('aria-label', `${iso}, cheapest ${formatPrice(price)}`);
        if (state.selectedDate === iso) cell.classList.add('is-selected');

        const dotColor = cheapestAirlineColor(iso);
        if (dotColor) {
          const dot = document.createElement('span');
          dot.className = 'calendar__cell__dot';
          dot.style.background = dotColor;
          dot.setAttribute('aria-hidden', 'true');
          cell.appendChild(dot);
        }

        cell.addEventListener('click', () => {
          state.selectedDate = iso;
          state.selectedFlight = null;
          renderAll();
          $('drilldown-panel').scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
        cell.addEventListener('keydown', (e) => {
          if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); cell.click(); }
        });
      }
      root.appendChild(cell);
      cursor.setDate(cursor.getDate() + 1);
      if (cursor > end && ((cursor.getDay() + 6) % 7) === 0) break;
    }

    const legend = document.createElement('div');
    legend.className = 'calendar-legend';
    legend.setAttribute('aria-hidden', 'true');
    legend.innerHTML = `
      <span>${formatPrice(range.min)}</span>
      <div class="calendar-legend__bar"></div>
      <span>${formatPrice(range.max)}</span>
    `;
    root.insertAdjacentElement('afterend', legend);
  }

  function wireCalendarNav() {
    const months = availableMonths();
    const prev = $('cal-prev'), next = $('cal-next');
    if (!prev || !next) return;
    prev.addEventListener('click', () => {
      const idx = months.indexOf(state.calendarMonth);
      if (idx > 0) { state.calendarMonth = months[idx - 1]; renderCalendar(); }
    });
    next.addEventListener('click', () => {
      const idx = months.indexOf(state.calendarMonth);
      if (idx < months.length - 1) { state.calendarMonth = months[idx + 1]; renderCalendar(); }
    });
  }

  function flightsForSelectedDate() {
    if (!state.selectedDate) return [];
    const out = [];
    activeRoutes().forEach((route) => {
      const list = ((DATA.flights[route] || {})[state.selectedDate]) || [];
      list.forEach((f) => {
        if (airlinePasses(f.airline)) out.push({ ...f, route });
      });
    });
    return out;
  }

  function renderDrilldown() {
    const title = $('drilldown-title');
    const root = $('drilldown');
    const sortBar = $('drilldown-sort');
    const historyWrap = $('price-history-wrap');

    if (!state.selectedDate) {
      title.textContent = 'Pick a day in the calendar';
      sortBar.innerHTML = '';
      root.innerHTML = '';
      historyWrap.classList.add('is-hidden');
      destroyChart('priceHistory');
      return;
    }

    title.textContent = `Flights on ${formatDate(state.selectedDate)}`;
    const flights = flightsForSelectedDate();
    if (flights.length === 0) {
      sortBar.innerHTML = '';
      root.innerHTML = `<div class="empty-state">No flights match the current filters on this day.</div>`;
      historyWrap.classList.add('is-hidden');
      destroyChart('priceHistory');
      return;
    }

    // Sort pills
    sortBar.innerHTML = '';
    [['price', 'Sort by price'], ['time', 'Sort by dep. time']].forEach(([mode, label]) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'filter-chip' + (state.drilldownSort === mode ? ' is-active' : '');
      btn.textContent = label;
      btn.addEventListener('click', () => { state.drilldownSort = mode; renderDrilldown(); });
      sortBar.appendChild(btn);
    });

    // Sort flights
    if (state.drilldownSort === 'price') {
      flights.sort((a, b) => a.latest_cents - b.latest_cents);
    } else {
      flights.sort((a, b) => a.dep_time.localeCompare(b.dep_time));
    }

    root.className = 'flight-list';
    root.innerHTML = '';
    flights.forEach((f) => {
      const row = document.createElement('button');
      row.type = 'button';
      row.className = 'flight-row' + (
        state.selectedFlight &&
        state.selectedFlight.airline === f.airline &&
        state.selectedFlight.dep_time === f.dep_time &&
        state.selectedFlight.route === f.route ? ' is-selected' : ''
      );
      const overnight = f.overnight ? `<span class="flight-row__overnight">+1</span>` : '';
      // Trajectory arrow: green ↓ for down, red ↑ for up, gray → for stable, none for null.
      let trajectoryHtml = '';
      if (f.trajectory === 'down') {
        const pct = f.trajectory_pct !== null ? Math.abs(Math.round(f.trajectory_pct)) + '%' : '';
        trajectoryHtml = `<span class="flight-row__trajectory flight-row__trajectory--down" aria-label="down ${pct}">↓</span>`;
      } else if (f.trajectory === 'up') {
        const pct = f.trajectory_pct !== null ? Math.abs(Math.round(f.trajectory_pct)) + '%' : '';
        trajectoryHtml = `<span class="flight-row__trajectory flight-row__trajectory--up" aria-label="up ${pct}">↑</span>`;
      } else if (f.trajectory === 'stable') {
        trajectoryHtml = `<span class="flight-row__trajectory flight-row__trajectory--stable" aria-label="stable">→</span>`;
      }
      // airlineColor() returns one of: a fixed hex/white/orange constant or a
      // synthesised hsl(deg,70%,50%) — both safe inside a style attribute.
      row.innerHTML = `
        <span class="airline-swatch" style="background:${airlineColor(f.airline)};
              ${AIRLINE_OUTLINE.has(f.airline) ? 'border-color:var(--color-brown);' : ''}"></span>
        <span>${escapeHtml(f.airline)} <small>(${escapeHtml(f.route)})</small></span>
        <span class="flight-row__time">${escapeHtml(f.dep_time)} → ${escapeHtml(f.arr_time)} ${overnight}</span>
        <span class="flight-row__time">${Math.floor(f.duration_minutes / 60)}h ${f.duration_minutes % 60}m</span>
        <span><strong>${formatPrice(f.latest_cents)}</strong>${trajectoryHtml}</span>
      `;
      row.addEventListener('click', () => {
        state.selectedFlight = { airline: f.airline, dep_time: f.dep_time, route: f.route };
        renderDrilldown();
      });
      root.appendChild(row);
    });

    // Price-history chart + verdict card for the selected flight
    if (!state.selectedFlight) {
      historyWrap.classList.add('is-hidden');
      destroyChart('priceHistory');
      renderVerdict(null);
      return;
    }
    const chosen = flights.find((f) =>
      f.airline === state.selectedFlight.airline &&
      f.dep_time === state.selectedFlight.dep_time &&
      f.route === state.selectedFlight.route
    );
    if (!chosen) {
      historyWrap.classList.add('is-hidden');
      destroyChart('priceHistory');
      renderVerdict(null);
      return;
    }
    historyWrap.classList.remove('is-hidden');
    renderVerdict(chosen);
    drawPriceHistory(chosen);
  }

  function drawPriceHistory(flight) {
    destroyChart('priceHistory');
    const ctx = $('price-history-chart');
    charts.priceHistory = new Chart(ctx, {
      type: 'line',
      data: {
        labels: flight.history.map((h) => h.obs_date),
        datasets: [{
          label: `${flight.airline} ${flight.dep_time}`,
          data: flight.history.map((h) => h.price_cents / 100),
          borderColor: airlineColor(flight.airline),
          backgroundColor: 'rgba(192, 57, 43, 0.10)',
          spanGaps: false,
          borderWidth: 2,
          pointRadius: 3,
          pointHoverRadius: 5,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (ctx) => `€${Math.round(ctx.parsed.y)} (${flight.history[ctx.dataIndex].days_before} days before)`,
            },
          },
        },
        scales: {
          x: { title: { display: true, text: 'Observation date' } },
          y: { title: { display: true, text: 'Price (€)' }, beginAtZero: false },
        },
      },
    });
    chartA11ySummary(ctx, flight.history.map((h) => ({
      'observation date': h.obs_date,
      'days before': h.days_before,
      'price (EUR)': Math.round(h.price_cents / 100),
    })));
  }

  function renderTrends() {
    destroyChart('marketTrend');
    destroyChart('leadtime');

    const headline = $('sweet-spot-headline');
    const routes = activeRoutes().filter((r) => DATA.analysis[r]);
    if (routes.length === 0) {
      headline.textContent = '';
      return;
    }

    // Market trend — one line per active route, X = obs_date, Y = min_cents/100
    const marketDatasets = routes.map((r) => {
      const trend = DATA.analysis[r].market_trend || [];
      return {
        label: r,
        data: trend.map((t) => ({ x: t.obs_date, y: t.min_cents / 100 })),
        borderColor: r === 'CPH-AMS' ? 'var(--color-red)' : 'var(--color-route-back)',
        backgroundColor: r === 'CPH-AMS' ? 'rgba(192,57,43,0.10)' : 'rgba(41,128,185,0.10)',
        spanGaps: false,
        borderWidth: 2,
        pointRadius: 2,
      };
    });
    const allDates = Array.from(new Set(
      routes.flatMap((r) => (DATA.analysis[r].market_trend || []).map((t) => t.obs_date))
    )).sort();
    charts.marketTrend = new Chart($('market-trend-chart'), {
      type: 'line',
      data: { labels: allDates, datasets: marketDatasets },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          title: { display: true, text: 'Market trend — cheapest seen on each scrape day' },
          tooltip: { callbacks: { label: (c) => `${c.dataset.label}: €${Math.round(c.parsed.y)}` } },
        },
        scales: { y: { title: { display: true, text: 'Price (€)' } } },
      },
    });

    // Three datasets per route: Q1 boundary, Q3 boundary (filled back to Q1 = IQR band), mean line.
    const leadDatasets = routes.flatMap((r) => {
      const curve = DATA.analysis[r].lead_time_curve || [];
      const bandAlpha = r === 'CPH-AMS' ? 'rgba(192,57,43,' : 'rgba(41,128,185,';
      return [
        {
          label: `${r} Q1`,
          data: curve.map((c) => ({ x: c.days_before, y: c.q1_cents / 100 })),
          borderColor: bandAlpha + '0)',
          backgroundColor: bandAlpha + '0)',
          fill: false,
          pointRadius: 0,
          spanGaps: false,
        },
        {
          label: `${r} IQR`,
          data: curve.map((c) => ({ x: c.days_before, y: c.q3_cents / 100 })),
          borderColor: bandAlpha + '0)',
          backgroundColor: bandAlpha + '0.15)',
          fill: '-1',
          pointRadius: 0,
          spanGaps: false,
        },
        {
          label: r,
          data: curve.map((c) => ({ x: c.days_before, y: c.mean_cents / 100 })),
          borderColor: r === 'CPH-AMS' ? 'var(--color-red)' : 'var(--color-route-back)',
          fill: false,
          spanGaps: false,
          borderWidth: 2,
          pointRadius: 2,
        },
      ];
    });
    const youAreHerePlugin = {
      id: 'youAreHere',
      afterDraw(chart) {
        if (!state.selectedDate) return;
        const todayMs = new Date().setHours(0, 0, 0, 0);
        const depMs   = new Date(state.selectedDate).setHours(0, 0, 0, 0);
        const daysUntilDep = Math.round((depMs - todayMs) / 86400000);
        if (daysUntilDep < 0) return;
        const { ctx, chartArea, scales } = chart;
        const xPx = scales.x.getPixelForValue(daysUntilDep);
        if (xPx < chartArea.left || xPx > chartArea.right) return;
        ctx.save();
        ctx.setLineDash([5, 3]);
        ctx.strokeStyle = 'rgba(0,0,0,0.5)';
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(xPx, chartArea.top);
        ctx.lineTo(xPx, chartArea.bottom);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.font = '11px sans-serif';
        ctx.fillStyle = 'rgba(0,0,0,0.55)';
        ctx.fillText('You are here', xPx + 4, chartArea.top + 14);
        ctx.restore();
      },
    };
    charts.leadtime = new Chart($('leadtime-chart'), {
      type: 'line',
      data: { datasets: leadDatasets },
      plugins: [youAreHerePlugin],
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          title: {
            display: true,
            text: 'Mean price by days-before-departure (descriptive history; not a prediction)',
          },
          legend: {
            labels: {
              filter: (item) => !item.text.endsWith(' Q1') && !item.text.endsWith(' IQR'),
            },
          },
        },
        scales: {
          x: {
            type: 'linear', reverse: true,
            title: { display: true, text: 'Days before departure' },
          },
          y: { title: { display: true, text: 'Mean price (€)' } },
        },
      },
    });

    const lines = routes.map((r) => {
      const days = DATA.analysis[r].sweet_spot_days;
      return days !== undefined ? `${r}: cheapest mean at ~${days} days ahead` : '';
    }).filter(Boolean);
    headline.textContent = lines.join(' · ');
  }

  function renderHistograms() {
    destroyChart('histogramOut');
    destroyChart('histogramBack');

    const canvasFor = { 'CPH-AMS': 'histogram-out', 'AMS-CPH': 'histogram-back' };
    const slotFor   = { 'CPH-AMS': 'histogramOut', 'AMS-CPH': 'histogramBack' };

    ['CPH-AMS', 'AMS-CPH'].forEach((route) => {
      const summary = DATA.summary[route];
      if (!summary) return;

      const histogram = summary.histogram || {};
      const airlines = Object.keys(histogram)
        .filter(airlinePasses)
        .sort();
      const allBins = Array.from(new Set(
        airlines.flatMap((a) => histogram[a].map((b) => b.bin_low))
      )).sort((a, b) => a - b);

      const datasets = airlines.map((airline) => {
        const byBin = Object.fromEntries(histogram[airline].map((b) => [b.bin_low, b.count]));
        return {
          label: airline,
          data: allBins.map((bl) => byBin[bl] || 0),
          backgroundColor: airlineColor(airline),
          borderColor: AIRLINE_OUTLINE.has(airline) ? 'var(--color-brown)' : airlineColor(airline),
          borderWidth: AIRLINE_OUTLINE.has(airline) ? 1.5 : 0,
        };
      });

      charts[slotFor[route]] = new Chart($(canvasFor[route]), {
        type: 'bar',
        data: {
          labels: allBins.map((bl) => `€${(bl / 100).toFixed(0)}`),
          datasets,
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: {
            title: { display: true, text: `${route} — price distribution (€5 bins)` },
            legend: { position: 'right' },
            tooltip: {
              callbacks: {
                label:  (c)     => `${c.dataset.label}: ${c.parsed.y} obs`,
                footer: (items) => `Total: ${items.reduce((s, i) => s + i.parsed.y, 0)} obs`,
              },
            },
          },
          scales: {
            x: { stacked: true, title: { display: true, text: 'Price bin' } },
            y: { stacked: true, beginAtZero: true, title: { display: true, text: 'Observation count' } },
          },
        },
      });
      const summaryRows = [];
      airlines.forEach((airline) => {
        histogram[airline].forEach((b) => {
          summaryRows.push({
            route,
            airline,
            'price bin (EUR)': `${(b.bin_low / 100).toFixed(0)}–${((b.bin_low + 500) / 100).toFixed(0)}`,
            count: b.count,
          });
        });
      });
      chartA11ySummary($(canvasFor[route]), summaryRows);
    });
  }

  function renderWeekendPairs() {
    const root = $('weekend-pairs');
    root.innerHTML = '';
    root.className = 'pairs-tables';

    const routesWithPairs = ['CPH-AMS', 'AMS-CPH'].filter(
      (r) => DATA.summary[r] && (DATA.summary[r].weekend_pairs || []).length > 0
    );
    if (routesWithPairs.length === 0) {
      root.innerHTML = `<div class="empty-state">No weekend pairs found in the current data window.</div>`;
      return;
    }
    routesWithPairs.forEach((route) => {
      const pairs = DATA.summary[route].weekend_pairs;
      const tableHtml = `
        <table class="pairs-table" aria-label="Cheapest weekend pairs for ${escapeHtml(route)}">
          <caption>${escapeHtml(route)} weekend pairs (Fri outbound + Sun inbound)</caption>
          <thead>
            <tr>
              <th>Fri date</th><th>Out</th><th>Out time</th><th>Out €</th>
              <th>Sun date</th><th>Back</th><th>Back time</th><th>Back €</th>
              <th>Total €</th>
            </tr>
          </thead>
          <tbody>
            ${pairs.map((p) => `
              <tr>
                <td>${escapeHtml(formatDate(p.fri_date))}</td>
                <td>${escapeHtml(p.fri_airline)}</td>
                <td>${escapeHtml(p.fri_dep)}</td>
                <td>${formatPrice(p.fri_cents)}</td>
                <td>${escapeHtml(formatDate(p.sun_date))}</td>
                <td>${escapeHtml(p.sun_airline)}</td>
                <td>${escapeHtml(p.sun_dep)}</td>
                <td>${formatPrice(p.sun_cents)}</td>
                <td><strong>${formatPrice(p.total_cents)}</strong></td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      `;
      root.insertAdjacentHTML('beforeend', tableHtml);
    });
  }

  function renderFooterCharts() {
    destroyChart('dow');
    destroyChart('month');

    const routes = activeRoutes().filter((r) => DATA.analysis[r]);
    if (routes.length === 0) return;

    const ROUTE_COLORS = {
      'CPH-AMS': 'rgba(192,57,43,0.65)',
      'AMS-CPH': 'rgba(107,62,38,0.65)',
    };

    function makeGroupedChart(canvas, field, keyField, title) {
      const allKeys = Array.from(new Set(
        routes.flatMap((r) => (DATA.analysis[r][field] || []).map((e) => e[keyField]))
      )).sort((a, b) => a - b);

      const labels = allKeys.map((k) => {
        for (const r of routes) {
          const entry = (DATA.analysis[r][field] || []).find((e) => e[keyField] === k);
          if (entry) return entry.label;
        }
        return String(k);
      });

      const datasets = routes.map((r) => {
        const byKey = Object.fromEntries(
          (DATA.analysis[r][field] || []).map((e) => [e[keyField], e.mean_cents])
        );
        return {
          label: r,
          data: allKeys.map((k) => byKey[k] != null ? byKey[k] / 100 : null),
          backgroundColor: ROUTE_COLORS[r] || 'rgba(107,62,38,0.5)',
          borderColor: 'rgba(107,62,38,0.4)',
          borderWidth: 1,
        };
      });

      return new Chart(canvas, {
        type: 'bar',
        data: { labels, datasets },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: {
            legend: { display: true, position: 'top' },
            title: { display: true, text: title },
            tooltip: {
              callbacks: { label: (c) => `${c.dataset.label}: €${Math.round(c.parsed.y)}` },
            },
          },
          scales: { y: { beginAtZero: false, title: { display: true, text: 'Mean price (€)' } } },
        },
      });
    }

    charts.dow   = makeGroupedChart($('dow-chart'),   'day_of_week', 'dow',   'Mean price by day of week');
    charts.month = makeGroupedChart($('month-chart'), 'month',       'month', 'Mean price by month');
  }

  const _DOW_LABELS_SHORT = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

  function renderTimeheat() {
    const pairs = [
      { route: 'CPH-AMS', slot: 'timeheatOut', canvasId: 'timeheat-out' },
      { route: 'AMS-CPH', slot: 'timeheatBack', canvasId: 'timeheat-back' },
    ];

    pairs.forEach(({ route, slot, canvasId }) => {
      // Clear any previous draw state stored on the canvas element.
      const canvas = $(canvasId);
      if (!canvas) return;
      if (charts[slot]) { charts[slot] = null; }
      canvas._heatCells = null;

      const routeData = DATA.analysis[route];
      const matrix = routeData ? (routeData.time_of_day_matrix || []) : [];

      // Always show both directions — this chart is exempt from the direction filter.
      const visible = matrix;

      if (!visible.length) {
        const ctx = canvas.getContext('2d');
        const W = canvas.offsetWidth || 360;
        canvas.width = W; canvas.height = 80;
        ctx.clearRect(0, 0, W, 80);
        ctx.fillStyle = 'rgba(107,62,38,0.4)';
        ctx.font = '13px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(`No data for ${route}`, W / 2, 44);
        return;
      }

      // Determine axis ranges.
      const hours = Array.from(new Set(visible.map((e) => e.hour))).sort((a, b) => a - b);
      const dows = [0, 1, 2, 3, 4, 5, 6];
      const allCents = visible.map((e) => e.mean_cents);
      const priceRange = { min: Math.min(...allCents), max: Math.max(...allCents) };

      // Layout constants.
      const PAD_LEFT = 36, PAD_TOP = 18, PAD_BOTTOM = 24, PAD_RIGHT = 8;
      const CELL_H = 24;
      const totalH = PAD_TOP + dows.length * CELL_H + PAD_BOTTOM;
      const W = Math.max(canvas.offsetWidth || 480, 280);
      const gridW = W - PAD_LEFT - PAD_RIGHT;
      const CELL_W = Math.floor(gridW / hours.length);
      canvas.width = W;
      canvas.height = totalH;

      const ctx = canvas.getContext('2d');
      ctx.clearRect(0, 0, W, totalH);

      // Build a lookup for fast cell access.
      const lookup = new Map();
      visible.forEach((e) => lookup.set(`${e.dow}_${e.hour}`, e));

      // Store cell rectangles for hover detection.
      const cells = [];

      dows.forEach((dow, ri) => {
        const y = PAD_TOP + ri * CELL_H;
        hours.forEach((hour, ci) => {
          const x = PAD_LEFT + ci * CELL_W;
          const entry = lookup.get(`${dow}_${hour}`);
          if (entry) {
            ctx.fillStyle = priceTint(entry.mean_cents, priceRange);
            ctx.fillRect(x, y, CELL_W - 1, CELL_H - 1);
            cells.push({ x, y, w: CELL_W - 1, h: CELL_H - 1, dow, hour, mean_cents: entry.mean_cents });
          } else {
            ctx.fillStyle = 'rgba(200,200,200,0.12)';
            ctx.fillRect(x, y, CELL_W - 1, CELL_H - 1);
          }
        });
        // Row label (day name).
        ctx.fillStyle = 'rgba(107,62,38,0.8)';
        ctx.font = '11px sans-serif';
        ctx.textAlign = 'right';
        ctx.textBaseline = 'middle';
        ctx.fillText(_DOW_LABELS_SHORT[dow], PAD_LEFT - 4, y + CELL_H / 2);
      });

      // Column labels (hours).
      ctx.fillStyle = 'rgba(107,62,38,0.8)';
      ctx.font = '10px sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      hours.forEach((hour, ci) => {
        if (ci % 2 === 0 || hours.length <= 8) {
          const x = PAD_LEFT + ci * CELL_W + CELL_W / 2;
          ctx.fillText(`${String(hour).padStart(2, '0')}h`, x, PAD_TOP + dows.length * CELL_H + 4);
        }
      });

      // Route label at top.
      ctx.fillStyle = 'rgba(107,62,38,0.6)';
      ctx.font = 'bold 11px sans-serif';
      ctx.textAlign = 'left';
      ctx.textBaseline = 'top';
      ctx.fillText(route, PAD_LEFT, 3);

      // Store cells for hover tooltip.
      canvas._heatCells = cells;
      charts[slot] = true;  // mark as drawn

      // Wire hover tooltip (idempotent — remove any previous listener first).
      if (canvas._heatMouseHandler) canvas.removeEventListener('mousemove', canvas._heatMouseHandler);
      if (canvas._heatLeaveHandler) canvas.removeEventListener('mouseleave', canvas._heatLeaveHandler);

      let tooltip = canvas._heatTooltip;
      if (!tooltip) {
        tooltip = document.createElement('div');
        tooltip.style.cssText = (
          'position:fixed;pointer-events:none;display:none;' +
          'background:rgba(43,26,16,0.9);color:#f3e7c9;' +
          'font-size:12px;padding:6px 10px;border-radius:4px;z-index:100;'
        );
        document.body.appendChild(tooltip);
        canvas._heatTooltip = tooltip;
      }

      canvas._heatMouseHandler = (e) => {
        const rect = canvas.getBoundingClientRect();
        const mx = (e.clientX - rect.left) * (canvas.width / rect.width);
        const my = (e.clientY - rect.top) * (canvas.height / rect.height);
        const hit = cells.find((c) => mx >= c.x && mx < c.x + c.w && my >= c.y && my < c.y + c.h);
        if (hit) {
          tooltip.textContent = `${_DOW_LABELS_SHORT[hit.dow]} ${String(hit.hour).padStart(2,'0')}:00–${String(hit.hour+1).padStart(2,'0')}:00 · €${Math.round(hit.mean_cents / 100)}`;
          tooltip.style.display = 'block';
          tooltip.style.left = `${e.clientX + 12}px`;
          tooltip.style.top  = `${e.clientY - 8}px`;
        } else {
          tooltip.style.display = 'none';
        }
      };
      canvas._heatLeaveHandler = () => { tooltip.style.display = 'none'; };
      canvas.addEventListener('mousemove', canvas._heatMouseHandler);
      canvas.addEventListener('mouseleave', canvas._heatLeaveHandler);
    });
  }

  function renderNormProgress() {
    destroyChart('normProg');
    // Always show both directions — this chart is exempt from the direction filter.
    const routes = ['CPH-AMS', 'AMS-CPH'].filter((r) => DATA.analysis[r]);
    if (routes.length === 0) return;

    const datasets = routes.map((r) => {
      const prog = DATA.analysis[r].normalized_price_progression || [];
      return {
        label: r,
        data: prog.map((e) => ({ x: e.days_before, y: e.mean_pct_change })),
        borderColor: r === 'CPH-AMS' ? 'var(--color-red)' : 'var(--color-route-back)',
        backgroundColor: 'transparent',
        spanGaps: false,
        borderWidth: 2,
        pointRadius: 2,
        fill: false,
      };
    });

    charts.normProg = new Chart($('normprog-chart'), {
      type: 'line',
      data: { datasets },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          title: { display: true, text: '% price change vs. earliest observation (0% = no change from baseline)' },
          tooltip: {
            callbacks: {
              label: (c) => `${c.dataset.label}: ${c.parsed.y >= 0 ? '+' : ''}${c.parsed.y.toFixed(1)}% vs earliest`,
            },
          },
        },
        scales: {
          x: {
            type: 'linear', reverse: true,
            title: { display: true, text: 'Days before departure' },
          },
          y: {
            title: { display: true, text: '% change vs. earliest observation' },
            ticks: { callback: (v) => `${v >= 0 ? '+' : ''}${v}%` },
          },
        },
      },
    });
  }

  function renderVerdict(flight) {
    const card = $('verdict-card');
    if (!card) return;
    if (!flight) {
      card.innerHTML = '';
      card.classList.add('is-hidden');
      return;
    }
    const { percentile, historical_mean_cents, latest_cents, airline, dep_time, route } = flight;

    let verdictText, verdictCls;
    if (percentile === null || percentile === undefined) {
      verdictText = 'Not enough data yet to assess this price';
      verdictCls = '';
    } else if (percentile <= 15) {
      verdictText = 'Great time to buy';
      verdictCls = 'is-good';
    } else if (percentile <= 25) {
      verdictText = 'Good time to buy';
      verdictCls = 'is-good';
    } else if (percentile <= 75) {
      verdictText = 'Fair price';
      verdictCls = 'is-fair';
    } else {
      verdictText = 'Above average';
      verdictCls = 'is-bad';
    }

    let vsAvgText = '';
    if (historical_mean_cents && latest_cents) {
      const diff = Math.round((historical_mean_cents - latest_cents) / historical_mean_cents * 100);
      vsAvgText = diff >= 0
        ? `${diff}% below historical average`
        : `${Math.abs(diff)}% above historical average`;
    }

    card.innerHTML = `
      <p class="verdict-card__header">${escapeHtml(airline)} ${escapeHtml(dep_time)} · ${escapeHtml(route || '')}</p>
      <div class="verdict-card__rows">
        <span>Current price</span><span><strong>${formatPrice(latest_cents)}</strong></span>
        ${historical_mean_cents ? `<span>Historical avg</span><span>${formatPrice(historical_mean_cents)}</span>` : ''}
        ${vsAvgText ? `<span>You are seeing</span><span>${escapeHtml(vsAvgText)}</span>` : ''}
      </div>
      <p class="verdict-card__verdict ${escapeHtml(verdictCls)}">${escapeHtml(verdictText)}</p>
    `;
    card.classList.remove('is-hidden');
  }

  function renderHero() {
    // Primary route for hero data. When "both" is active, CPH-AMS is used.
    const primaryRoute = activeRoutes()[0];
    const routeData = DATA.analysis[primaryRoute];

    function fill(id, html) { const el = $(id); if (el) el.innerHTML = html; }

    const fallback = '<p class="hero-card__fallback">Not enough data yet.</p>';
    if (!routeData) {
      fill('hero-best-time', fallback);
      fill('hero-market', fallback);
      fill('hero-book-when', fallback);
      return;
    }

    // Card 1 — Best time to visit
    const btv = routeData.best_time_to_visit || {};
    const cm  = btv.cheapest_month || {};
    const cdow = btv.cheapest_dow || {};
    const le  = btv.lowest_ever || {};
    const leDate = le.departure_date ? formatDate(le.departure_date) : '—';
    const leLine = le.price_cents
      ? `${formatPrice(le.price_cents)} — ${escapeHtml(le.airline || '')}, ${escapeHtml(primaryRoute)}, ${escapeHtml(leDate)}`
      : '—';
    fill('hero-best-time', `
      <h3 class="hero-card__title">Best time to visit</h3>
      <p>Cheapest month: <strong>${escapeHtml(cm.label || '—')}</strong>${cm.mean_cents ? ' (avg ' + formatPrice(cm.mean_cents) + ')' : ''}</p>
      <p>Cheapest day: <strong>${escapeHtml(cdow.label || '—')}</strong>${cdow.mean_cents ? ' (avg ' + formatPrice(cdow.mean_cents) + ')' : ''}</p>
      <p>Lowest ever: <strong>${leLine}</strong></p>
    `);

    // Card 2 — Market direction
    const md = routeData.market_direction || {};
    const arrowGlyph = md.trend === 'down'   ? '↓'
                     : md.trend === 'up'    ? '↑'
                     :                        '→';
    const arrowCls   = md.trend === 'down'   ? 'hero-card__arrow--down'
                     : md.trend === 'up'    ? 'hero-card__arrow--up'
                     : md.trend === 'stable' ? 'hero-card__arrow--stable'
                     :                        'hero-card__arrow--stable';
    fill('hero-market', `
      <h3 class="hero-card__title">Market direction</h3>
      <p><span class="hero-card__arrow ${escapeHtml(arrowCls)}" aria-hidden="true">${arrowGlyph}</span>
         ${escapeHtml(md.label || 'Prices stable this week')}</p>
      <p class="hero-card__sub">Based on last 14 days of observations</p>
    `);

    // Card 3 — When to book
    const sweetSpotDays = routeData.sweet_spot_days;
    let bookByText = '—';
    if (sweetSpotDays !== undefined && sweetSpotDays !== null) {
      const t = new Date();
      t.setDate(t.getDate() + sweetSpotDays);
      bookByText = formatDate(
        `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, '0')}-${String(t.getDate()).padStart(2, '0')}`
      );
    }
    fill('hero-book-when', `
      <h3 class="hero-card__title">When to book</h3>
      <p>Sweet spot: <strong>~${sweetSpotDays !== undefined && sweetSpotDays !== null ? sweetSpotDays : '—'} days</strong> before departure</p>
      <p>Book by <strong>${escapeHtml(bookByText)}</strong> for cheapest fares</p>
    `);
  }

  function renderAll() {
    renderHeader();
    renderHero();
    renderCalendar();
    renderDrilldown();
    renderTrends();
    renderHistograms();
    renderWeekendPairs();
    renderFooterCharts();
    renderTimeheat();
    renderNormProgress();
  }

  // ───── Filter wiring ───────────────────────────────────────────────────────
  function wireFilters() {
    // CHANGE (UX): inject a small uppercase label before each group of chips
    // so the role is obvious without a tooltip. Cleared each render so we
    // never accumulate duplicates.
    function ensureLabel(container, text) {
      const existing = container.previousElementSibling;
      if (existing && existing.classList && existing.classList.contains('filters__label')) {
        existing.textContent = text;
        return;
      }
      const label = document.createElement('span');
      label.className = 'filters__label';
      label.textContent = text;
      container.parentNode.insertBefore(label, container);
    }

    // Route toggle
    const routes = ['CPH-AMS', 'AMS-CPH', 'both'];
    const routeContainer = $('route-toggle');
    routeContainer.innerHTML = '';
    ensureLabel(routeContainer, 'Route');
    routes.forEach((r) => {
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'filter-chip' + (state.route === r ? ' is-active' : '');
      chip.textContent = r === 'both' ? 'Both' : r;
      chip.dataset.route = r;
      chip.addEventListener('click', () => {
        state.route = r;
        state.selectedDate = null;
        state.selectedFlight = null;
        Array.from(routeContainer.children).forEach((c) => {
          c.classList.toggle('is-active', c.dataset.route === r);
        });
        renderAll();
      });
      routeContainer.appendChild(chip);
    });

    // Airline filter — chips for every airline in metadata
    const airlineContainer = $('airline-filter');
    airlineContainer.innerHTML = '';
    ensureLabel(airlineContainer, 'Airline');
    const airlines = (DATA.metadata.airlines || []).slice().sort();
    airlines.forEach((a) => {
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'filter-chip';
      chip.style.borderLeft = `8px solid ${airlineColor(a)}`;
      chip.textContent = a;
      chip.dataset.airline = a;
      chip.addEventListener('click', () => {
        if (state.airlineFilter.has(a)) state.airlineFilter.delete(a);
        else state.airlineFilter.add(a);
        chip.classList.toggle('is-active', state.airlineFilter.has(a));
        renderAll();
      });
      airlineContainer.appendChild(chip);
    });
  }

  /** Active routes derived from state.route. */
  function activeRoutes() {
    if (state.route === 'both') return ['CPH-AMS', 'AMS-CPH'];
    return [state.route];
  }

  /** True if a row's airline survives the current filter. Empty filter = all pass. */
  function airlinePasses(airline) {
    return state.airlineFilter.size === 0 || state.airlineFilter.has(airline);
  }

  // ───── Boot ────────────────────────────────────────────────────────────────
  function main() {
    try { assertRequiredDomIds(); }
    catch (e) { fatalBanner(e.message); console.error(e); return; }

    DATA = loadData();
    if (typeof window.Chart === 'undefined') {
      fatalBanner('Chart.js failed to load — re-run scripts/fetch_vendor.py.');
      return;
    }

    if (!DATA.metadata || (DATA.metadata.total_rows ?? 0) === 0) {
      document.querySelector('main').innerHTML =
        '<div class="empty-state">No flight observations available. ' +
        'Re-run the scheduler or the CSV builder to generate data.</div>';
      return;
    }

    // Initialise calendarMonth to the first month in the data range.
    const firstMonth = (DATA.metadata.date_range || {}).from;
    state.calendarMonth = firstMonth ? firstMonth.slice(0, 7) : null;

    wireFilters();
    wireCalendarNav();
    renderAll();
    // Expose for debugging (read-only in spirit; do not write from outside)
    window.__tracker = { state, DATA };
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', main);
  } else {
    main();
  }
})();
