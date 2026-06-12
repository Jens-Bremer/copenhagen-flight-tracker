// ───── Price Volatility Index panel ──────────────────────────────────────────
// Two charts per route:
//   1. Horizontal bar chart — CV (coefficient of variation) per airline.
//   2. Line chart — 14-day rolling std dev of daily-minimum prices per airline.
// Reads DATA_PRICE_VOLATILITY_INDEX JSON blob.

function _viFormatEur(cents) {
  return `€${Math.round(cents / 100)}`;
}

function _viCvColor(cv) {
  // cv is a fraction (0.0–1.0+). Green < 0.20, yellow 0.20–0.40, red > 0.40.
  if (cv === null || cv === undefined) return 'rgba(180,180,180,0.7)';
  if (cv < 0.20) return 'rgba(39,174,96,0.75)';
  if (cv < 0.40) return 'rgba(243,156,18,0.75)';
  return 'rgba(192,57,43,0.75)';
}

function _viRenderEmpty(container, msg) {
  const p = document.createElement('p');
  p.style.cssText = 'color:#888;font-style:italic;margin:.5rem 0;';
  p.textContent = msg;
  container.appendChild(p);
}

function _viMakeCanvas(id, height) {
  const wrap = document.createElement('div');
  wrap.className = 'chart-wrap';
  wrap.style.cssText = `max-height:${height}px;`;
  const canvas = document.createElement('canvas');
  canvas.id = id;
  wrap.appendChild(canvas);
  return { wrap, canvas };
}

function _viRenderCvChart(canvas, bars) {
  const labels = bars.map((b) => b.airline);
  const values = bars.map((b) => b.cv !== null ? +(b.cv * 100).toFixed(1) : 0);
  const colors = bars.map((b) => _viCvColor(b.cv));

  new Chart(canvas, {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        label: 'CV (%)',
        data: values,
        backgroundColor: colors,
        borderRadius: 3,
      }],
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label(ctx) {
              const b = bars[ctx.dataIndex];
              const cv = b.cv !== null ? `CV ${(b.cv * 100).toFixed(1)}%` : 'CV n/a';
              return `${cv} · mean ${_viFormatEur(b.mean_cents)} · σ ${_viFormatEur(b.std_cents)} · n=${b.n}`;
            },
          },
        },
      },
      scales: {
        x: {
          title: { display: true, text: 'Coefficient of variation (%)' },
          beginAtZero: true,
        },
      },
    },
  });
}

function _viRenderRollingChart(canvas, rolling) {
  // Group by airline.
  const byAirline = {};
  rolling.forEach((pt) => {
    if (!byAirline[pt.airline]) byAirline[pt.airline] = [];
    byAirline[pt.airline].push(pt);
  });

  const datasets = Object.entries(byAirline).map(([airline, pts]) => {
    pts.sort((a, b) => a.obs_date.localeCompare(b.obs_date));
    const color = airlineColor(airline);
    return {
      label: airline,
      data: pts.map((p) => ({ x: p.obs_date, y: +(p.stddev_cents / 100).toFixed(2) })),
      borderColor: color,
      backgroundColor: color,
      pointRadius: 3,
      fill: false,
      tension: 0.3,
    };
  });

  new Chart(canvas, {
    type: 'line',
    data: { datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        tooltip: {
          callbacks: {
            label(ctx) {
              const pt = byAirline[ctx.dataset.label][ctx.dataIndex];
              return `${ctx.dataset.label}: σ ${_viFormatEur(pt.stddev_cents)} · min ${_viFormatEur(pt.daily_min_cents)} · n=${pt.n}`;
            },
          },
        },
      },
      scales: {
        x: { type: 'category', title: { display: true, text: 'Observation date' } },
        y: { title: { display: true, text: 'Std dev (€)' }, beginAtZero: true },
      },
    },
  });
}

function renderVolatilityIndex() {
  const container = document.getElementById('volatility-index-container');
  if (!container) return;
  container.innerHTML = '';

  const blob = document.getElementById('DATA_PRICE_VOLATILITY_INDEX');
  if (!blob) return;
  const text = blob.textContent.trim();
  if (!text) {
    _viRenderEmpty(container, 'Price Volatility Index — data not yet available.');
    return;
  }

  let data;
  try { data = JSON.parse(text); }
  catch (e) { console.error('Failed to parse DATA_PRICE_VOLATILITY_INDEX:', e); return; }

  const byRoute = (data && data.by_route) || {};
  const routes = Object.keys(byRoute).sort();
  if (routes.length === 0) {
    _viRenderEmpty(container, 'Price Volatility Index — not enough data yet (need ≥ 20 observations per airline).');
    return;
  }

  routes.forEach((route) => {
    const { cv_bars, rolling_stddev } = byRoute[route];

    const section = document.createElement('div');
    section.style.cssText = 'margin-bottom:2rem;';

    const heading = document.createElement('h3');
    heading.textContent = route;
    heading.style.cssText = 'font-size:1rem;margin:.75rem 0 .5rem;';
    section.appendChild(heading);

    // CV bar chart.
    if (cv_bars && cv_bars.length > 0) {
      const cvLabel = document.createElement('p');
      cvLabel.textContent = 'Coefficient of variation — lower = more predictable pricing';
      cvLabel.style.cssText = 'font-size:.8rem;color:#777;margin:0 0 .25rem;';
      section.appendChild(cvLabel);
      const barHeight = Math.max(160, cv_bars.length * 36);
      const { wrap: cvWrap, canvas: cvCanvas } = _viMakeCanvas(`vi-cv-${route}`, barHeight);
      section.appendChild(cvWrap);
      _viRenderCvChart(cvCanvas, cv_bars);
    } else {
      _viRenderEmpty(section, `${route}: not enough observations for CV bars (need ≥ 20 per airline).`);
    }

    // Rolling std dev line chart.
    if (rolling_stddev && rolling_stddev.length > 0) {
      const rollLabel = document.createElement('p');
      rollLabel.textContent = '14-day rolling std dev of daily-minimum prices';
      rollLabel.style.cssText = 'font-size:.8rem;color:#777;margin:.75rem 0 .25rem;';
      section.appendChild(rollLabel);
      const { wrap: rollWrap, canvas: rollCanvas } = _viMakeCanvas(`vi-roll-${route}`, 220);
      section.appendChild(rollWrap);
      _viRenderRollingChart(rollCanvas, rolling_stddev);
    } else {
      _viRenderEmpty(section, `${route}: not enough history for rolling volatility (need ≥ 7 obs-dates per airline).`);
    }

    container.appendChild(section);
  });
}
