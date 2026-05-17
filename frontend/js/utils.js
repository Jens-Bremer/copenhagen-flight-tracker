// ───── Tiny helpers ────────────────────────────────────────────────────────
function $(id) { return document.getElementById(id); }
function formatPrice(cents) { return '€' + Math.round(cents / 100); }

/** HTML-escape *s* for safe interpolation into `innerHTML`. Defends against
 *  attacker-controlled airline names from the upstream scraper. */
function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function formatDate(iso) {
  const [y, m, d] = iso.split('-').map(Number);
  return new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
    .format(new Date(y, m - 1, d));
}

function formatMonth(date) {
  return new Intl.DateTimeFormat('en-GB', { month: 'long', year: 'numeric' }).format(date);
}

function todayIso() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
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

/** Linear green→amber→red interpolation across [min, max], returned as CSS rgb. */
function priceTint(cents, range) {
  if (!range || range.max === range.min) return 'rgba(241, 196, 15, 0.35)';
  const t = (cents - range.min) / (range.max - range.min);     // 0 = cheap, 1 = expensive
  // 0=#3d7a3d green, 0.5=#e67e22 orange, 1=#c0392b red
  const lerp = (a, b, k) => Math.round(a + (b - a) * k);
  let r, g, b;
  if (t < 0.5) {
    const k = t * 2;
    r = lerp(61, 230, k); g = lerp(122, 126, k); b = lerp(61, 34, k);
  } else {
    const k = (t - 0.5) * 2;
    r = lerp(230, 192, k); g = lerp(126, 57, k); b = lerp(34, 43, k);
  }
  return `rgba(${r}, ${g}, ${b}, 0.32)`;
}

/** Build a visually-hidden table next to a chart canvas so screen readers
 *  can read the underlying data. `rows` is an array of objects whose keys
 *  become column headers. */
function chartA11ySummary(parentCanvas, rows) {
  const wrap = parentCanvas.parentElement;
  if (!wrap) return;
  let table = wrap.querySelector('.visually-hidden');
  if (!table) {
    table = document.createElement('div');
    table.className = 'visually-hidden';
    wrap.appendChild(table);
  }
  if (!rows.length) { table.innerHTML = ''; return; }
  table.innerHTML = `<table><thead><tr>${
    Object.keys(rows[0]).map((k) => `<th>${escapeHtml(k)}</th>`).join('')
  }</tr></thead><tbody>${
    rows.map((r) => '<tr>' + Object.values(r).map((v) => `<td>${escapeHtml(v)}</td>`).join('') + '</tr>').join('')
  }</tbody></table>`;
}

/** Return the palette colour for a given route string.
 *  Index is determined by position in DATA.metadata.routes. */
function routeColor(route) {
  const idx = DATA.metadata.routes.indexOf(route);
  return ROUTE_PALETTE[idx % ROUTE_PALETTE.length];
}
