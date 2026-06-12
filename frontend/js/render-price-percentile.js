// ───── Price-vs-history percentile verdict badges ───────────────────────────
// Renders a compact "cheap / typical / expensive" badge per (route, airline,
// lead-time bucket) into #price-percentile-container. Reads
// DATA_PRICE_PERCENTILE JSON blob.

const PERCENTILE_LABEL_COLOR = {
  cheap:     { bg: '#c8e6c9', fg: '#1b5e20' },  // green
  typical:   { bg: '#e8e8e8', fg: '#424242' },  // grey
  expensive: { bg: '#ffccbc', fg: '#b71c1c' },  // red
};

function _percentileFormatPrice(cents) {
  return `€${(cents / 100).toFixed(0)}`;
}

function _percentileFormatOrdinal(p) {
  const n = Math.round(p);
  const suffix =
    n >= 11 && n <= 13 ? 'th'
    : n % 10 === 1 ? 'st'
    : n % 10 === 2 ? 'nd'
    : n % 10 === 3 ? 'rd' : 'th';
  return `${n}${suffix}`;
}

function _percentileBuildBadge(bucket) {
  const colors = PERCENTILE_LABEL_COLOR[bucket.label] || PERCENTILE_LABEL_COLOR.typical;
  const el = document.createElement('div');
  el.className = 'price-percentile-badge';
  el.style.cssText =
    `display:inline-flex;flex-direction:column;align-items:flex-start;` +
    `padding:.5rem .75rem;margin:.25rem;border-radius:.5rem;` +
    `background:${colors.bg};color:${colors.fg};font-size:.85rem;line-height:1.2;`;
  const head = document.createElement('strong');
  head.textContent = `${bucket.airline} · ${_percentileFormatPrice(bucket.latest_price_cents)}`;
  el.appendChild(head);
  const sub = document.createElement('span');
  sub.textContent =
    `${_percentileFormatOrdinal(bucket.percentile)} pct · ${bucket.label} ` +
    `(${bucket.days_before}d out, n=${bucket.reference_n})`;
  el.appendChild(sub);
  return el;
}

function _percentileRenderEmpty(container, reason) {
  const msg = document.createElement('p');
  msg.className = 'price-percentile-empty';
  msg.style.cssText = 'color:#777;font-style:italic;margin:.5rem 0;';
  msg.textContent =
    reason === 'need_min_14_days_history'
      ? 'Price-vs-history verdict — not enough data yet (need ≥ 14 days of history).'
      : 'No price-vs-history verdicts available yet.';
  container.appendChild(msg);
}

function renderPricePercentile() {
  const container = document.getElementById('price-percentile-container');
  if (!container) return;
  container.innerHTML = '';

  const blob = document.getElementById('DATA_PRICE_PERCENTILE');
  if (!blob) return;
  const text = blob.textContent.trim();
  if (!text) {
    _percentileRenderEmpty(container, 'empty');
    return;
  }

  let data;
  try { data = JSON.parse(text); }
  catch (e) { console.error('Failed to parse DATA_PRICE_PERCENTILE:', e); return; }

  if (data && data.insufficient_data) {
    _percentileRenderEmpty(container, data.insufficient_data);
    return;
  }

  const buckets = (data && data.buckets) || [];
  if (buckets.length === 0) {
    _percentileRenderEmpty(container, 'empty');
    return;
  }

  // Group by route → one section per route.
  const byRoute = {};
  buckets.forEach((b) => {
    if (!byRoute[b.route]) byRoute[b.route] = [];
    byRoute[b.route].push(b);
  });

  Object.keys(byRoute).sort().forEach((route) => {
    const section = document.createElement('div');
    section.className = 'price-percentile-route';
    const h = document.createElement('h3');
    h.textContent = route;
    h.style.cssText = 'font-size:1rem;margin:.75rem 0 .25rem;';
    section.appendChild(h);
    const list = document.createElement('div');
    list.style.cssText = 'display:flex;flex-wrap:wrap;';
    byRoute[route].forEach((b) => list.appendChild(_percentileBuildBadge(b)));
    section.appendChild(list);
    container.appendChild(section);
  });
}
