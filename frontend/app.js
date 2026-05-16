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

  function renderCalendar()       { /* Task 15 */ }
  function renderDrilldown()      { /* Task 16 */ }
  function renderTrends()         { /* Task 17 */ }
  function renderHistograms()     { /* Task 18 */ }
  function renderWeekendPairs()   { /* Task 19 */ }
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
