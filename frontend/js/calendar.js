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

function cellFlightCount(iso) {
  let total = 0;
  activeRoutes().forEach((route) => {
    const v = (DATA.calendar[route] || {})[iso];
    if (v) total += (v.flight_count || 0);
  });
  return total;
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
    const count = cellFlightCount(iso);
    const countHtml = (price !== null && count > 0)
      ? `<span class="calendar__cell__count">${count === 1 ? '1 flight' : `${count} flights`}</span>`
      : '';
    cell.innerHTML = `
      <span class="calendar__cell__day">${cursor.getDate()}</span>
      <span class="calendar__cell__price">${price !== null ? formatPrice(price) : '—'}</span>
      ${countHtml}
      ${trajectoryHtmlStr}
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
