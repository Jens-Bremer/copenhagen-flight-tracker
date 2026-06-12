// ───── Price momentum + sweet-spot timing card ─────────────────────────────
// Renders a per-route "Timing" card. Reads DATA_MOMENTUM JSON blob.

const MOMENTUM_DIRECTION_GLYPH = {
  falling: '↓',
  flat:    '→',
  rising:  '↑',
};

const MOMENTUM_DIRECTION_COLOR = {
  falling: '#1b5e20',
  flat:    '#555',
  rising:  '#b71c1c',
};

function _momentumFormatPct(pct) {
  if (pct === null || pct === undefined) return '—';
  const sign = pct > 0 ? '+' : '';
  return `${sign}${pct.toFixed(1)}%`;
}

function _momentumFormatPrice(cents) {
  return `€${(cents / 100).toFixed(0)}`;
}

function _momentumRenderEmpty(container, history_days, min_days) {
  const msg = document.createElement('p');
  msg.style.cssText = 'color:#777;font-style:italic;margin:.5rem 0;';
  msg.textContent =
    `Timing — not enough data yet (have ${history_days || 0} day(s) of history; need ≥ ${min_days || 14}).`;
  container.appendChild(msg);
}

function _momentumBuildWindowChip(label, w) {
  const dir = w.direction;
  const color = MOMENTUM_DIRECTION_COLOR[dir] || '#555';
  const glyph = MOMENTUM_DIRECTION_GLYPH[dir] || '·';
  const chip = document.createElement('span');
  chip.style.cssText =
    `display:inline-flex;gap:.4rem;align-items:baseline;padding:.25rem .6rem;` +
    `margin-right:.5rem;border-radius:.5rem;background:#f3f3f3;color:${color};font-size:.9rem;`;
  chip.innerHTML =
    `<strong>${label}</strong> ` +
    `<span aria-hidden="true">${glyph}</span> ` +
    `<span>${_momentumFormatPct(w.pct_change)}</span> ` +
    `<span style="color:#888;">(n=${w.sample_days})</span>`;
  return chip;
}

function _momentumBuildSweetSpot(ss) {
  if (!ss) return null;
  const el = document.createElement('div');
  el.style.cssText = 'margin-top:.5rem;color:#333;font-size:.9rem;';
  el.textContent =
    `Cheapest historically ~${ss.days_before_low}–${ss.days_before_high} days out ` +
    `(median ${_momentumFormatPrice(ss.median_cents)}, n=${ss.sample_count}).`;
  return el;
}

function _momentumBuildRouteCard(route) {
  const card = document.createElement('div');
  card.className = 'momentum-card';
  card.style.cssText =
    'background:#fafafa;border-radius:.5rem;padding:.75rem 1rem;margin:.5rem 0;';
  const h = document.createElement('h3');
  h.textContent = `${route.route} · timing`;
  h.style.cssText = 'font-size:1rem;margin:0 0 .5rem;';
  card.appendChild(h);

  const chips = document.createElement('div');
  chips.appendChild(_momentumBuildWindowChip('Last 7d', route.recent_7d));
  chips.appendChild(_momentumBuildWindowChip('Last 14d', route.recent_14d));
  card.appendChild(chips);

  const ss = _momentumBuildSweetSpot(route.sweet_spot);
  if (ss) card.appendChild(ss);
  return card;
}

function renderMomentum() {
  const container = document.getElementById('momentum-container');
  if (!container) return;
  container.innerHTML = '';

  const blob = document.getElementById('DATA_MOMENTUM');
  if (!blob) return;
  const text = blob.textContent.trim();
  if (!text) {
    _momentumRenderEmpty(container, 0, 14);
    return;
  }

  let data;
  try { data = JSON.parse(text); }
  catch (e) { console.error('Failed to parse DATA_MOMENTUM:', e); return; }

  if (data && data.insufficient_data) {
    _momentumRenderEmpty(container, data.history_days, data.min_history_days);
    return;
  }
  const routes = (data && data.routes) || [];
  if (routes.length === 0) {
    _momentumRenderEmpty(container, data.history_days, data.min_history_days);
    return;
  }
  routes.forEach((r) => container.appendChild(_momentumBuildRouteCard(r)));
}
