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
      if (charts.leadtime) charts.leadtime.update();
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
