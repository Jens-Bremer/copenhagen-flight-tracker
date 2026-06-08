// ───── Airline trends chart renderer ────────────────────────────────────────
// Renders per-airline median price progressions with Q1→Q3 confidence bands
// using the stacked-dataset pattern (Q1 invisible → IQR fill → Median line).
// Two charts: one per route (CPH-AMS, AMS-CPH).

function renderAirlineTrends() {
  destroyChart('airline-trend-out');
  destroyChart('airline-trend-back');

  // Read the embedded JSON data blob from the page.
  const dataBlob = document.getElementById('DATA_AIRLINE_TRENDS');
  if (!dataBlob) return;

  let data;
  try {
    data = JSON.parse(dataBlob.textContent);
  } catch {
    return;
  }

  if (!data || typeof data !== 'object') return;

  const routes = Object.keys(data).sort();
  if (routes.length === 0) return;

  const isMobile = window.innerWidth < 430;

  // Render one chart per route.
  routes.forEach((route, routeIdx) => {
    const chartId = routeIdx === 0 ? 'airline-trend-out' : 'airline-trend-back';
    const container = document.getElementById(chartId);
    if (!container) return;

    const airlines = data[route] || [];

    // Handle empty route data.
    if (airlines.length === 0) {
      if (container.parentElement) {
        container.parentElement.innerHTML = `<div class="empty-state">No airline data for ${escapeHtml(route)}</div>`;
      }
      return;
    }

    // Build five datasets per airline: Q1 (invisible), IQR fill, Median line.
    // This matches the stacked-dataset pattern from renderTrends() in charts.js.
    const datasets = airlines.flatMap((airline) => {
      const color = airline.color;
      const series = airline.series || [];

      return [
        // Q1 boundary (invisible, anchor for IQR fill)
        {
          label: `${airline.airline} Q1`,
          data: series.map((s) => ({ x: s.days_before, y: s.p25_cents / 100 })),
          borderColor: hexToRgba(color, 0),
          backgroundColor: hexToRgba(color, 0),
          fill: false,
          pointRadius: 0,
          spanGaps: false,
        },
        // IQR fill (Q1 → Q3, semi-transparent band)
        {
          label: `${airline.airline} IQR`,
          data: series.map((s) => ({ x: s.days_before, y: s.p75_cents / 100 })),
          borderColor: hexToRgba(color, 0),
          backgroundColor: hexToRgba(color, 0.15),
          fill: '-1',  // Fill to Q1 (previous dataset)
          pointRadius: 0,
          spanGaps: false,
        },
        // Median line (visible, with points)
        {
          label: airline.airline,
          data: series.map((s) => ({ x: s.days_before, y: s.median_cents / 100 })),
          borderColor: color,
          backgroundColor: 'transparent',
          fill: false,
          spanGaps: false,
          borderWidth: 2,
          pointRadius: 2,
          pointBackgroundColor: color,
          pointBorderColor: color,
        },
      ];
    });

    // Create the Chart.js instance.
    charts[chartId] = new Chart(container, {
      type: 'line',
      data: { datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          title: {
            display: true,
            text: `${route} — median price by booking window`,
            font: { size: isMobile ? 13 : 14 },
          },
          legend: {
            labels: {
              // Filter out Q1 and IQR labels from legend.
              filter: (item) =>
                !item.text.endsWith(' Q1') &&
                !item.text.endsWith(' IQR'),
              font: { size: isMobile ? 10 : 12 },
            },
          },
          tooltip: {
            callbacks: {
              label: (ctx) => {
                // Skip band labels in tooltips.
                if (
                  ctx.dataset.label.endsWith(' Q1') ||
                  ctx.dataset.label.endsWith(' IQR')
                ) return null;

                const airline = ctx.dataset.label;
                const airlineData = data[route].find((a) => a.airline === airline);
                if (!airlineData) return null;

                const series = airlineData.series || [];
                const entry = series[ctx.dataIndex];
                const n = entry?.sample_count ?? '?';

                return `${airline}: €${ctx.parsed.y.toFixed(0)} (n=${n})`;
              },
            },
          },
        },
        scales: {
          x: {
            type: 'linear',
            reverse: true,
            title: { display: true, text: 'Days before departure' },
          },
          y: {
            title: { display: true, text: 'Median price (€)' },
            min: 0,
          },
        },
      },
    });
  });
}
