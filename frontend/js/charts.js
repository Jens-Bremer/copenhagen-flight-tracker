function renderTrends() {
  destroyChart('leadtime');

  const headline = $('sweet-spot-headline');
  const routes = activeRoutes().filter((r) => DATA.analysis[r]);
  if (routes.length === 0) {
    headline.textContent = '';
    return;
  }

  // Five datasets per route: min boundary, max band, Q1 boundary, IQR fill, mean line.
  // Odd-indexed routes get a dashed border for visual distinction.
  // Mean line segments with obs_count < 10 are rendered dashed to signal low confidence.
  const leadDatasets = routes.flatMap((r) => {
    const curve = DATA.analysis[r].lead_time_curve || [];
    const color = routeColor(r);
    const routeIdx = DATA.metadata.routes.indexOf(r);
    const isDashed = routeIdx % 2 === 1;
    return [
      // Min band (very faint, bottom boundary)
      {
        label: `${r} min`,
        data: curve.map((c) => ({ x: c.days_before, y: c.min_cents / 100 })),
        borderColor: hexToRgba(color, 0),
        backgroundColor: hexToRgba(color, 0),
        fill: false,
        pointRadius: 0,
        spanGaps: false,
      },
      // Max band (very faint fill back to min)
      {
        label: `${r} max`,
        data: curve.map((c) => ({ x: c.days_before, y: c.max_cents / 100 })),
        borderColor: hexToRgba(color, 0),
        backgroundColor: hexToRgba(color, 0.06),
        fill: '-1',
        pointRadius: 0,
        spanGaps: false,
      },
      // Q1 boundary (invisible, anchor for IQR fill)
      {
        label: `${r} Q1`,
        data: curve.map((c) => ({ x: c.days_before, y: c.q1_cents / 100 })),
        borderColor: hexToRgba(color, 0),
        backgroundColor: hexToRgba(color, 0),
        fill: false,
        pointRadius: 0,
        spanGaps: false,
      },
      // IQR band (fill from Q1 to Q3)
      {
        label: `${r} IQR`,
        data: curve.map((c) => ({ x: c.days_before, y: c.q3_cents / 100 })),
        borderColor: hexToRgba(color, 0),
        backgroundColor: hexToRgba(color, 0.15),
        fill: '-1',
        pointRadius: 0,
        spanGaps: false,
      },
      // Mean line — dashed where obs_count < 10
      {
        label: r,
        data: curve.map((c) => ({ x: c.days_before, y: c.mean_cents / 100 })),
        borderColor: color,
        fill: false,
        spanGaps: false,
        borderWidth: 2,
        pointRadius: (ctx) => (curve[ctx.dataIndex]?.obs_count ?? 10) < 10 ? 4 : 2,
        pointBackgroundColor: (ctx) => (curve[ctx.dataIndex]?.obs_count ?? 10) < 10
          ? 'transparent' : color,
        pointBorderColor: color,
        segment: {
          borderDash: (ctx) => {
            const obs = curve[ctx.p0DataIndex]?.obs_count ?? 10;
            const baseDash = isDashed ? [6, 4] : [];
            return obs < 10 ? [3, 3] : baseDash;
          },
        },
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
      if (state.selectedFlight) {
        const sf = state.selectedFlight;
        const dfl = ((DATA.flights || {})[sf.route] || {})[state.selectedDate] || [];
        const chosen = dfl.find(
          (f) => f.airline === sf.airline && f.dep_time === sf.dep_time
        );
        if (chosen && chosen.latest_cents) {
          const yPx = scales.y.getPixelForValue(chosen.latest_cents / 100);
          ctx.beginPath();
          ctx.arc(xPx, yPx, 6, 0, 2 * Math.PI);
          ctx.fillStyle = 'rgba(192,57,43,0.9)';
          ctx.fill();
          ctx.strokeStyle = '#fff';
          ctx.lineWidth = 2;
          ctx.stroke();
        }
      }
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
            filter: (item) =>
              !item.text.endsWith(' Q1') &&
              !item.text.endsWith(' IQR') &&
              !item.text.endsWith(' min') &&
              !item.text.endsWith(' max'),
          },
        },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              if (
                ctx.dataset.label.endsWith(' Q1') ||
                ctx.dataset.label.endsWith(' IQR') ||
                ctx.dataset.label.endsWith(' min') ||
                ctx.dataset.label.endsWith(' max')
              ) return null;
              const route = ctx.dataset.label;
              const curve = DATA.analysis[route]?.lead_time_curve || [];
              const entry = curve[ctx.dataIndex];
              const n = entry?.obs_count ?? '?';
              return `${route}: €${ctx.parsed.y.toFixed(0)} (n=${n})`;
            },
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
  // Destroy any existing histogram charts for all routes.
  (DATA.metadata.routes || []).forEach((r) => {
    const slot = 'histogram_' + r;
    if (charts[slot]) { charts[slot].destroy(); charts[slot] = null; }
  });

  const container = $('histograms-container');
  if (!container) return;
  container.innerHTML = '';

  (DATA.metadata.routes || []).forEach((route) => {
    const summary = DATA.summary[route];
    if (!summary) return;

    // Build a wrapper div with chart-wrap class and a canvas inside.
    const wrap = document.createElement('div');
    wrap.className = 'chart-wrap';
    const canvas = document.createElement('canvas');
    canvas.setAttribute('role', 'img');
    wrap.appendChild(canvas);
    container.appendChild(wrap);

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

    const slot = 'histogram_' + route;
    charts[slot] = new Chart(canvas, {
      type: 'bar',
      data: {
        labels: allBins.map((bl) => `€${(bl / 100).toFixed(0)}`),
        datasets,
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          title: { display: true, text: `${route} — price distribution (€5 bins)` },
          legend: { position: 'bottom', align: 'center', labels: { boxWidth: 12, boxHeight: 12, padding: 8 } },
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
    chartA11ySummary(canvas, summaryRows);
  });
}

function renderWeekendPairs() {
  const root = $('weekend-pairs');
  root.innerHTML = '';
  root.className = 'pairs-tables';

  const routesWithPairs = (DATA.metadata.routes || []).filter(
    (r) => DATA.summary[r] && (DATA.summary[r].weekend_pairs || []).length > 0
  );
  if (routesWithPairs.length === 0) {
    root.innerHTML = `<div class="empty-state">No weekend pairs found in the current data window.</div>`;
    return;
  }
  routesWithPairs.forEach((route) => {
    const pairs = DATA.summary[route].weekend_pairs;
    const tableHtml = `
      <table class="pairs-table" data-route="${escapeHtml(route)}" aria-label="Cheapest weekend pairs for ${escapeHtml(route)}">
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
    // Set caption background to route palette colour after insertion.
    const table = root.querySelector(`table[data-route="${CSS.escape(route)}"]`);
    if (table) {
      const caption = table.querySelector('caption');
      if (caption) caption.style.backgroundColor = routeColor(route);
    }
  });
}

function renderFooterCharts() {
  destroyChart('dow');
  destroyChart('month');

  const routes = activeRoutes().filter((r) => DATA.calendar[r]);
  if (routes.length === 0) return;

  // Build raw price arrays per group key from calendar min prices across all active routes.
  function buildPriceGroups(keyFn) {
    const groups = {};
    routes.forEach((route) => {
      Object.entries(DATA.calendar[route] || {}).forEach(([dateStr, info]) => {
        if (!info.min_cents) return;
        const k = keyFn(dateStr);
        if (k === null) return;
        (groups[k] = groups[k] || []).push(info.min_cents / 100);
      });
    });
    return groups;
  }

  const DOW_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  const MONTH_LABELS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

  const dowGroups = buildPriceGroups(
    (d) => (new Date(d + 'T00:00:00').getDay() + 6) % 7  // JS Sun=0 → Mon=0…Sun=6
  );
  const monthGroups = buildPriceGroups(
    (d) => new Date(d + 'T00:00:00').getMonth()  // 0=Jan…11=Dec
  );

  function makeBoxplotChart(canvas, groups, allLabels, title) {
    const keys = allLabels.map((_, i) => i).filter((k) => (groups[k] || []).length > 0);
    return new Chart(canvas, {
      type: 'boxplot',
      data: {
        labels: keys.map((k) => allLabels[k]),
        datasets: [{
          label: 'Price (€)',
          data: keys.map((k) => groups[k]),
          backgroundColor: 'rgba(107,62,38,0.2)',
          borderColor: 'rgba(107,62,38,0.7)',
          borderWidth: 1.5,
          outlierBackgroundColor: 'rgba(192,57,43,0.6)',
          outlierRadius: 3,
          medianColor: 'rgba(43,26,16,0.9)',
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          title: { display: true, text: title },
          tooltip: {
            callbacks: {
              label: (c) => {
                const s = c.parsed;
                if (!s) return '';
                return [
                  `Median: €${Math.round(s.median ?? s.y ?? 0)}`,
                  `Q1–Q3: €${Math.round(s.q1 ?? 0)}–€${Math.round(s.q3 ?? 0)}`,
                  `Min/Max: €${Math.round(s.min ?? 0)} / €${Math.round(s.max ?? 0)}`,
                ];
              },
            },
          },
        },
        scales: { y: { beginAtZero: false, title: { display: true, text: 'Price (€)' } } },
      },
    });
  }

  charts.dow   = makeBoxplotChart($('dow-chart'),   dowGroups,   DOW_LABELS,   'Price spread by day of week');
  charts.month = makeBoxplotChart($('month-chart'), monthGroups, MONTH_LABELS, 'Price spread by month');
}

function renderAirlineBoxplots() {
  (DATA.metadata.routes || []).forEach((r) => {
    const slot = 'airlineBox_' + r;
    if (charts[slot]) { charts[slot].destroy(); charts[slot] = null; }
  });

  const container = $('airline-boxplots-container');
  if (!container) return;
  container.innerHTML = '';

  const routes = activeRoutes();
  if (routes.length === 0) return;

  routes.forEach((route) => {
    const byAirline = {};
    Object.values(DATA.flights[route] || {}).forEach((flightList) => {
      flightList.forEach((f) => {
        if (!airlinePasses(f.airline) || !f.latest_cents) return;
        (byAirline[f.airline] = byAirline[f.airline] || []).push(f.latest_cents / 100);
      });
    });

    const airlines = Object.keys(byAirline).sort();
    if (airlines.length === 0) return;

    const wrap = document.createElement('div');
    wrap.className = 'chart-wrap';
    const canvas = document.createElement('canvas');
    canvas.setAttribute('role', 'img');
    canvas.setAttribute('aria-label', `${route} price spread by airline`);
    wrap.appendChild(canvas);
    container.appendChild(wrap);

    const slot = 'airlineBox_' + route;
    charts[slot] = new Chart(canvas, {
      type: 'boxplot',
      data: {
        labels: airlines,
        datasets: [{
          label: route,
          data: airlines.map((a) => byAirline[a]),
          backgroundColor: airlines.map((a) => hexToRgba(airlineColor(a), 0.3)),
          borderColor: airlines.map((a) => airlineColor(a)),
          borderWidth: 1.5,
          outlierBackgroundColor: 'rgba(192,57,43,0.5)',
          outlierRadius: 3,
          medianColor: 'rgba(43,26,16,0.9)',
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          title: { display: true, text: `${route} — price spread by airline` },
          tooltip: {
            callbacks: {
              label: (c) => {
                const s = c.parsed;
                if (!s) return '';
                return [
                  `Median: €${Math.round(s.median ?? s.y ?? 0)}`,
                  `Q1–Q3: €${Math.round(s.q1 ?? 0)}–€${Math.round(s.q3 ?? 0)}`,
                  `Min/Max: €${Math.round(s.min ?? 0)} / €${Math.round(s.max ?? 0)}`,
                ];
              },
            },
          },
        },
        scales: { y: { beginAtZero: false, title: { display: true, text: 'Price (€)' } } },
      },
    });
  });
}

function renderTimeheat() {
  // Destroy any existing timeheat charts.
  (DATA.metadata.routes || []).forEach((r) => {
    const slot = 'timeheat_' + r;
    if (charts[slot]) { charts[slot] = null; }
  });

  const container = $('timeheat-container');
  if (!container) return;
  container.innerHTML = '';

  (DATA.metadata.routes || []).forEach((route) => {
    // Build a canvas for this route dynamically.
    const canvas = document.createElement('canvas');
    canvas.setAttribute('aria-label', `${route} price heatmap by time of day`);
    container.appendChild(canvas);

    const slot = 'timeheat_' + route;

    // Clear any previous draw state stored on the canvas element.
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
  // Always show all routes — this chart is exempt from the direction filter.
  const routes = (DATA.metadata.routes || []).filter((r) => DATA.analysis[r]);
  if (routes.length === 0) return;

  // Three datasets per route: Q1 (transparent), IQR fill, mean visible line.
  // Odd-indexed routes get a dashed line for visual distinction (same as renderTrends).
  const datasets = routes.flatMap((r) => {
    const prog = DATA.analysis[r].normalized_price_progression || [];
    const color = routeColor(r);
    const routeIdx = DATA.metadata.routes.indexOf(r);
    const isDashed = routeIdx % 2 === 1;
    return [
      {
        label: `${r} Q1`,
        data: prog.map((e) => ({ x: e.days_before, y: e.q1_pct_change !== undefined ? e.q1_pct_change : e.mean_pct_change })),
        borderColor: hexToRgba(color, 0),
        backgroundColor: hexToRgba(color, 0),
        fill: false,
        pointRadius: 0,
        spanGaps: false,
      },
      {
        label: `${r} IQR`,
        data: prog.map((e) => ({ x: e.days_before, y: e.q3_pct_change !== undefined ? e.q3_pct_change : e.mean_pct_change })),
        borderColor: hexToRgba(color, 0),
        backgroundColor: hexToRgba(color, 0.15),
        fill: '-1',
        pointRadius: 0,
        spanGaps: false,
      },
      {
        label: r,
        data: prog.map((e) => ({ x: e.days_before, y: e.mean_pct_change })),
        borderColor: color,
        borderDash: isDashed ? [6, 4] : [],
        backgroundColor: 'transparent',
        spanGaps: false,
        borderWidth: 2,
        pointRadius: 2,
        fill: false,
      },
    ];
  });

  charts.normProg = new Chart($('normprog-chart'), {
    type: 'line',
    data: { datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        title: { display: true, text: '% price change vs. earliest observation (0% = no change from baseline)' },
        legend: {
          labels: {
            filter: (item) => !item.text.endsWith(' Q1') && !item.text.endsWith(' IQR'),
          },
        },
        tooltip: {
          callbacks: {
            label: (c) => {
              if (c.dataset.label.endsWith(' Q1') || c.dataset.label.endsWith(' IQR')) return null;
              return `${c.dataset.label}: ${c.parsed.y >= 0 ? '+' : ''}${c.parsed.y.toFixed(1)}% vs earliest`;
            },
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

