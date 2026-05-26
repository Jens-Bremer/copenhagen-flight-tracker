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

function renderHero() {
  // Primary route for hero data. When "both" is active, first route is used.
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

  // Card 3 — When to book (#113: anchor to selected date when set; never show
  // today+N if no date selected — that's misleading for future trips)
  const sweetSpotDays = routeData.sweet_spot_days;
  let bookWhenHtml;
  if (sweetSpotDays === undefined || sweetSpotDays === null) {
    bookWhenHtml = fallback;
  } else if (state.selectedDate) {
    const dep = new Date(state.selectedDate + 'T00:00:00');
    const bookBy = new Date(dep);
    bookBy.setDate(dep.getDate() - sweetSpotDays);
    const bookByIso = `${bookBy.getFullYear()}-${String(bookBy.getMonth() + 1).padStart(2, '0')}-${String(bookBy.getDate()).padStart(2, '0')}`;
    bookWhenHtml = `
      <h3 class="hero-card__title">When to book</h3>
      <p>For your selected departure (${escapeHtml(formatDate(state.selectedDate))}), the cheapest historical window is <strong>~${sweetSpotDays} days</strong> before → book by <strong>${escapeHtml(formatDate(bookByIso))}</strong>.</p>
    `;
  } else {
    bookWhenHtml = `
      <h3 class="hero-card__title">When to book</h3>
      <p>Sweet spot: <strong>~${sweetSpotDays} days</strong> before departure</p>
      <p class="hero-card__sub">Select a departure date on the calendar for a personalised book-by date.</p>
    `;
  }
  fill('hero-book-when', bookWhenHtml);
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
  renderAirlineBoxplots();
  renderTimeheat();
  renderNormProgress();
}

// ───── Boot ────────────────────────────────────────────────────────────────
async function main() {
  try { assertRequiredDomIds(); }
  catch (e) { fatalBanner(e.message); console.error(e); return; }

  DATA = await loadData();
  if (typeof window.Chart === 'undefined') {
    fatalBanner('Chart.js failed to load — re-run scripts/fetch_vendor.py.');
    return;
  }
  if (typeof Chart !== 'undefined') {
    Chart.defaults.devicePixelRatio = window.devicePixelRatio || 1;
  }

  if (!DATA.metadata || (DATA.metadata.total_rows ?? 0) === 0) {
    document.querySelector('main').innerHTML =
      '<div class="empty-state">No flight observations available. ' +
      'Re-run the scheduler or the CSV builder to generate data.</div>';
    return;
  }

  // Initialise route filter to the first route in metadata.
  const allRoutes = DATA.metadata.routes || [];
  state.route = allRoutes.length > 1 ? 'both' : (allRoutes[0] || null);

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
