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
    selectedDate: null,      // 'YYYY-MM-DD' | null
    selectedFlight: null,    // { airline, dep_time } | null
    airlineFilter: new Set() // empty Set = all airlines visible
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
  };
  function destroyChart(slot) {
    if (charts[slot]) { charts[slot].destroy(); charts[slot] = null; }
  }

  // ───── Tiny helpers ────────────────────────────────────────────────────────
  function $(id) { return document.getElementById(id); }
  function formatPrice(cents) { return '€' + (cents / 100).toFixed(2); }
  function formatDate(iso) {
    const [y, m, d] = iso.split('-').map(Number);
    return new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
      .format(new Date(y, m - 1, d));
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

  // ───── Panel renderers (each lives in its own task; stubbed here) ──────────
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

  function renderCalendar() {
    const root = $('calendar');
    root.innerHTML = '';
    root.className = 'calendar';

    const range = calendarPriceRange();
    if (!range) {
      root.outerHTML = `<div id="calendar" class="empty-state">No flights match the current filters.</div>`;
      return;
    }

    // Weekday header row
    ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].forEach((w) => {
      const el = document.createElement('div');
      el.className = 'calendar__weekday';
      el.textContent = w;
      root.appendChild(el);
    });

    // Build the chronological grid from the metadata's date_range, padded so
    // the first row aligns to Monday.
    const fromIso = DATA.metadata.date_range.from;
    const toIso   = DATA.metadata.date_range.to;
    if (!fromIso || !toIso) return;
    const [fy, fm, fd] = fromIso.split('-').map(Number);
    const [ty, tm, td] = toIso.split('-').map(Number);
    let cursor = new Date(fy, fm - 1, fd);
    const end = new Date(ty, tm - 1, td);
    const padDays = (cursor.getDay() + 6) % 7;                   // 0=Mon...6=Sun
    cursor.setDate(cursor.getDate() - padDays);

    // Cheapest across active routes for cell rendering
    function cellPrice(iso) {
      let cheapest = Infinity;
      activeRoutes().forEach((route) => {
        const v = (DATA.calendar[route] || {})[iso];
        if (v && v.min_cents < cheapest) cheapest = v.min_cents;
      });
      return isFinite(cheapest) ? cheapest : null;
    }

    while (cursor <= end || ((cursor.getDay() + 6) % 7) !== 0) {
      const iso = cursor.toISOString().slice(0, 10);
      const cell = document.createElement('div');
      const price = cellPrice(iso);
      cell.className = 'calendar__cell' + (price === null ? ' is-empty' : '');
      cell.dataset.date = iso;
      cell.innerHTML = `
        <span class="calendar__cell__day">${cursor.getDate()}</span>
        <span class="calendar__cell__price">${price !== null ? formatPrice(price) : '—'}</span>
      `;
      if (price !== null) {
        cell.style.background = priceTint(price, range);
        cell.tabIndex = 0;
        cell.setAttribute('role', 'button');
        cell.setAttribute('aria-label', `${iso}, cheapest ${formatPrice(price)}`);
        if (state.selectedDate === iso) cell.classList.add('is-selected');
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
    const historyWrap = $('price-history-wrap');

    if (!state.selectedDate) {
      title.textContent = 'Pick a day in the calendar';
      root.innerHTML = '';
      historyWrap.classList.add('is-hidden');
      destroyChart('priceHistory');
      return;
    }

    title.textContent = `Flights on ${formatDate(state.selectedDate)}`;
    const flights = flightsForSelectedDate();
    if (flights.length === 0) {
      root.innerHTML = `<div class="empty-state">No flights match the current filters on this day.</div>`;
      historyWrap.classList.add('is-hidden');
      destroyChart('priceHistory');
      return;
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
      row.innerHTML = `
        <span class="airline-swatch" style="background:${airlineColor(f.airline)};
              ${AIRLINE_OUTLINE.has(f.airline) ? 'border-color:var(--color-brown);' : ''}"></span>
        <span>${f.airline} <small>(${f.route})</small></span>
        <span class="flight-row__time">${f.dep_time} → ${f.arr_time} ${overnight}</span>
        <span class="flight-row__time">${Math.floor(f.duration_minutes / 60)}h ${f.duration_minutes % 60}m</span>
        <span><strong>${formatPrice(f.latest_cents)}</strong></span>
      `;
      row.addEventListener('click', () => {
        state.selectedFlight = { airline: f.airline, dep_time: f.dep_time, route: f.route };
        renderDrilldown();
      });
      root.appendChild(row);
    });

    // Price-history chart for the selected flight
    if (!state.selectedFlight) {
      historyWrap.classList.add('is-hidden');
      destroyChart('priceHistory');
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
      return;
    }
    historyWrap.classList.remove('is-hidden');
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
              label: (ctx) => `€${ctx.parsed.y.toFixed(2)} (${flight.history[ctx.dataIndex].days_before} days before)`,
            },
          },
        },
        scales: {
          x: { title: { display: true, text: 'Observation date' } },
          y: { title: { display: true, text: 'Price (€)' }, beginAtZero: false },
        },
      },
    });
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
        borderColor: r === 'CPH-AMS' ? 'var(--color-red)' : 'var(--color-brown)',
        backgroundColor: 'rgba(192, 57, 43, 0.10)',
        spanGaps: false,
        borderWidth: 2,
        pointRadius: 2,
      };
    });
    // Compute the union of obs_dates for shared labels
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
          tooltip: { callbacks: { label: (c) => `${c.dataset.label}: €${c.parsed.y.toFixed(2)}` } },
        },
        scales: { y: { title: { display: true, text: 'Price (€)' } } },
      },
    });

    // Lead-time curve
    const leadDatasets = routes.map((r) => {
      const curve = DATA.analysis[r].lead_time_curve || [];
      return {
        label: r,
        data: curve.map((c) => ({ x: c.days_before, y: c.mean_cents / 100 })),
        borderColor: r === 'CPH-AMS' ? 'var(--color-red)' : 'var(--color-brown)',
        spanGaps: false,
        borderWidth: 2,
        pointRadius: 2,
      };
    });
    charts.leadtime = new Chart($('leadtime-chart'), {
      type: 'line',
      data: { datasets: leadDatasets },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          title: { display: true, text: 'Mean price by days-before-departure (descriptive history; not a prediction)' },
        },
        scales: {
          x: { type: 'linear', reverse: true, title: { display: true, text: 'Days before departure' } },
          y: { title: { display: true, text: 'Mean price (€)' } },
        },
      },
    });

    // Headline: "Book ~N days ahead" per route
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

      // Union of all bin_lows across airlines, then airline order = legend order
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
          labels: allBins.map((bl) => `€${(bl / 100).toFixed(0)}–€${((bl + 500) / 100).toFixed(0)}`),
          datasets,
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: {
            title: { display: true, text: `${route} — price distribution (€5 bins)` },
            legend: { position: 'right' },
            tooltip: {
              callbacks: {
                label: (c) => `${c.dataset.label}: ${c.parsed.y} obs`,
              },
            },
          },
          scales: {
            x: { stacked: false, title: { display: true, text: 'Price bin' } },
            y: { beginAtZero: true, title: { display: true, text: 'Observation count' } },
          },
        },
      });
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
        <table class="pairs-table" aria-label="Cheapest weekend pairs for ${route}">
          <caption>${route} weekend pairs (Fri outbound + Sun inbound)</caption>
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
                <td>${formatDate(p.fri_date)}</td>
                <td>${p.fri_airline}</td>
                <td>${p.fri_dep}</td>
                <td>${formatPrice(p.fri_cents)}</td>
                <td>${formatDate(p.sun_date)}</td>
                <td>${p.sun_airline}</td>
                <td>${p.sun_dep}</td>
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
  function renderFooterCharts()   { /* Task 20 */ }

  function renderAll() {
    renderHeader();
    renderCalendar();
    renderDrilldown();
    renderTrends();
    renderHistograms();
    renderWeekendPairs();
    renderFooterCharts();
  }

  // ───── Filter wiring ───────────────────────────────────────────────────────
  function wireFilters() {
    // Route toggle
    const routes = ['CPH-AMS', 'AMS-CPH', 'both'];
    const routeContainer = $('route-toggle');
    routeContainer.innerHTML = '';
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
    DATA = loadData();
    if (typeof window.Chart === 'undefined') {
      console.error('Chart.js failed to load — charts will be missing.');
    }
    wireFilters();
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
