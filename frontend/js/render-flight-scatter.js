// ───── Live Flight Prices scatter panel ──────────────────────────────────────
// One Chart.js scatter chart per route. Each point is one bookable flight at
// its latest observed price (x = days before departure, y = price in €),
// coloured by airline. Hovering a point reveals that flight's full price
// history as a faint line and fades all other points, plus a custom tooltip
// pinned to the right of the point. Reads the DATA_FLIGHT_SCATTER JSON blob.

const _FSC_MONTHS = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
];

function _fscEur(cents) {
  return `€${Math.round(cents / 100)}`;
}

// Format an ISO date string ("2026-08-04") as "04 Aug 2026".
function _fscFormatDate(iso) {
  const [y, m, d] = iso.split('-').map(Number);
  return `${String(d).padStart(2, '0')} ${_FSC_MONTHS[m - 1]} ${y}`;
}

// Return *color* with alpha applied. Handles the hex values from
// AIRLINE_COLORS and the hsl() fallback from airlineColor().
function _fscWithAlpha(color, alpha) {
  if (color.startsWith('#')) return hexToRgba(color, alpha);
  if (color.startsWith('hsl(')) return `hsla(${color.slice(4, -1)},${alpha})`;
  return color;
}

function _fscInjectStyles() {
  if (document.getElementById('fsc-tooltip-styles')) return;
  const style = document.createElement('style');
  style.id = 'fsc-tooltip-styles';
  style.textContent = `
#flight-scatter-tooltip {
  position: fixed;
  pointer-events: none;
  z-index: 1000;
  background: rgba(255,255,255,0.97);
  border: 1px solid #ccc;
  border-radius: 4px;
  padding: 6px 10px;
  font-size: 0.82rem;
  line-height: 1.6;
  box-shadow: 0 2px 6px rgba(0,0,0,0.15);
  min-width: 110px;
}
.fsc-tooltip { display: flex; flex-direction: column; gap: 1px; }
.fsc-dow-date { font-weight: 600; color: #333; }
.fsc-time { color: #555; }
.fsc-price { font-weight: 700; color: #1a1a1a; font-size: 1rem; }
.fsc-airline { color: #666; font-size: 0.78rem; }`;
  document.head.appendChild(style);
}

function _scatterClearHover(chart) {
  const history = chart.data.datasets.find((d) => d.label === '__history__');
  if (history) history.data = [];
  chart.data.datasets.forEach((ds) => {
    if (ds.label === '__history__') return;
    ds.backgroundColor = ds._fullColor;
    ds.pointBackgroundColor = undefined;
  });
  chart.update('none');
  const tip = document.getElementById('flight-scatter-tooltip');
  if (tip) tip.remove();
}

function _scatterShowHover(chart, flight, datasetIndex, index, event) {
  // Fade every scatter point, then restore only the hovered point.
  chart.data.datasets.forEach((ds, di) => {
    if (ds.label === '__history__') return;
    const faded = _fscWithAlpha(ds._fullColor, 0.08);
    ds.backgroundColor = faded;
    if (di === datasetIndex) {
      const arr = ds.data.map(() => faded);
      arr[index] = ds._fullColor;
      ds.pointBackgroundColor = arr;
    } else {
      ds.pointBackgroundColor = undefined;
    }
  });

  const history = chart.data.datasets.find((d) => d.label === '__history__');
  if (history) {
    history.data = (flight.history || []).map((h) => ({
      x: h.days_before,
      y: Math.round(h.price_cents / 100),
    }));
  }
  chart.update('none');

  // Custom tooltip — only when we have a real mouse position.
  if (!event || !event.native) return;
  _fscInjectStyles();
  let tip = document.getElementById('flight-scatter-tooltip');
  if (!tip) {
    tip = document.createElement('div');
    tip.id = 'flight-scatter-tooltip';
    document.body.appendChild(tip);
  }
  tip.innerHTML = `<div class="fsc-tooltip">` +
    `<span class="fsc-dow-date">${escapeHtml(flight.dep_dow)} ${escapeHtml(_fscFormatDate(flight.dep_date))}</span>` +
    `<span class="fsc-time">${escapeHtml(flight.dep_time)}</span>` +
    `<span class="fsc-price">${escapeHtml(_fscEur(flight.price_cents))}</span>` +
    `<span class="fsc-airline">${escapeHtml(flight.airline)}</span>` +
    `</div>`;
  const rect = chart.canvas.getBoundingClientRect();
  const px = chart.scales.x.getPixelForValue(flight.days_before);
  const py = chart.scales.y.getPixelForValue(Math.round(flight.price_cents / 100));
  tip.style.left = `${rect.left + px + 12}px`;
  tip.style.top = `${rect.top + py - 20}px`;
}

function _fscBuildChart(canvas, flights) {
  // One scatter dataset per airline.
  const byAirline = {};
  flights.forEach((f) => {
    (byAirline[f.airline] = byAirline[f.airline] || []).push(f);
  });

  const datasets = Object.keys(byAirline).map((airline) => {
    const color = airlineColor(airline);
    return {
      label: airline,
      data: byAirline[airline].map((f) => ({
        x: f.days_before,
        y: Math.round(f.price_cents / 100),
        _flight: f,
      })),
      backgroundColor: color,
      _fullColor: color,
      pointRadius: 5,
      pointHoverRadius: 7,
      type: 'scatter',
    };
  });

  // Shared hidden history line, populated on hover.
  datasets.push({
    label: '__history__',
    data: [],
    type: 'line',
    borderColor: 'rgba(100,100,100,0.5)',
    backgroundColor: 'transparent',
    pointRadius: 2,
    borderWidth: 1.5,
    spanGaps: false,
    order: 0,
  });

  const chart = new Chart(canvas, {
    type: 'scatter',
    data: { datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      plugins: {
        tooltip: { enabled: false },
        legend: {
          labels: { filter: (item) => item.text !== '__history__' },
        },
      },
      scales: {
        x: {
          type: 'linear',
          reverse: true,
          title: { display: true, text: 'Days before departure' },
        },
        y: {
          type: 'linear',
          title: { display: true, text: 'Price (€)' },
          ticks: { callback: (value) => `€${Math.round(value)}` },
        },
      },
      onHover: (event, activeElements) => {
        if (!activeElements || activeElements.length === 0) {
          _scatterClearHover(chart);
          return;
        }
        const el = activeElements[0];
        const ds = chart.data.datasets[el.datasetIndex];
        const point = ds && ds.data[el.index];
        if (!point || !point._flight) return;
        _scatterShowHover(chart, point._flight, el.datasetIndex, el.index, event);
      },
    },
  });

  canvas.addEventListener('mouseleave', () => _scatterClearHover(chart));
  return chart;
}

function renderFlightScatter() {
  destroyChart('flight-scatter-out');
  destroyChart('flight-scatter-back');

  const ids = ['flight-scatter-out', 'flight-scatter-back'];
  const blob = document.getElementById('DATA_FLIGHT_SCATTER');
  if (!blob || !blob.textContent.trim()) return;

  let data;
  try {
    data = JSON.parse(blob.textContent);
  } catch {
    return;
  }

  const routes = data && data.routes ? Object.keys(data.routes).sort() : [];
  if (routes.length === 0) {
    ids.forEach((id) => {
      const c = document.getElementById(id);
      if (c && c.parentElement) {
        c.parentElement.innerHTML = '<div class="empty-state">No current flight data available.</div>';
      }
    });
    return;
  }

  routes.slice(0, ids.length).forEach((route, idx) => {
    const id = ids[idx];
    const canvas = document.getElementById(id);
    if (!canvas) return;
    const flights = data.routes[route] || [];
    if (flights.length === 0) {
      if (canvas.parentElement) {
        canvas.parentElement.innerHTML = '<div class="empty-state">No current flight data available.</div>';
      }
      return;
    }
    charts[id] = _fscBuildChart(canvas, flights);
  });
}
