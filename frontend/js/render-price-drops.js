// ───── Recent price drops panel ─────────────────────────────────────────────
// Renders a compact table of recent persisted price drops. Reads
// DATA_PRICE_DROPS JSON blob.

function _dropsFormatPrice(cents) {
  return `€${(cents / 100).toFixed(0)}`;
}

function _dropsFormatPct(pct) {
  if (pct === null || pct === undefined) return '—';
  return `${pct.toFixed(1)}%`;
}

function _dropsFormatDeparture(iso) {
  // "2026-08-12T07:25:00" → "12 Aug, 07:25"
  if (!iso) return '';
  try {
    const [datePart, timePart] = iso.split('T');
    const [, m, d] = datePart.split('-');
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    const month = months[parseInt(m, 10) - 1] || m;
    const time = timePart ? timePart.slice(0, 5) : '';
    return `${parseInt(d, 10)} ${month}${time ? ', ' + time : ''}`;
  } catch { return iso; }
}

function _dropsRenderEmpty(container, reason, history_days) {
  const msg = document.createElement('p');
  msg.style.cssText = 'color:#777;font-style:italic;margin:.5rem 0;';
  if (reason === 'need_min_14_days_history') {
    msg.textContent = `Recent price drops — not enough history yet (have ${history_days || 0} day(s); need ≥ 14).`;
  } else {
    msg.textContent = 'No notable persisted price drops in the recent reference window.';
  }
  container.appendChild(msg);
}

function _dropsBuildTable(drops) {
  const table = document.createElement('table');
  table.className = 'price-drops-table';
  table.style.cssText = 'width:100%;border-collapse:collapse;font-size:.9rem;';
  const thead = document.createElement('thead');
  thead.innerHTML =
    '<tr style="text-align:left;background:#fafafa;">' +
    '<th style="padding:.4rem .5rem;">Route</th>' +
    '<th style="padding:.4rem .5rem;">Airline</th>' +
    '<th style="padding:.4rem .5rem;">Departure</th>' +
    '<th style="padding:.4rem .5rem;text-align:right;">Now</th>' +
    '<th style="padding:.4rem .5rem;text-align:right;">Typical</th>' +
    '<th style="padding:.4rem .5rem;text-align:right;">Δ</th>' +
    '<th style="padding:.4rem .5rem;text-align:right;">Pct</th>' +
    '<th style="padding:.4rem .5rem;text-align:right;">Persisted</th>' +
    '</tr>';
  table.appendChild(thead);

  const tbody = document.createElement('tbody');
  drops.forEach((d) => {
    const tr = document.createElement('tr');
    tr.style.cssText = 'border-top:1px solid #eee;';
    const cells = [
      d.route,
      d.airline,
      _dropsFormatDeparture(d.departure_at) + ` (${d.departure_date})`,
      _dropsFormatPrice(d.current_price_cents),
      _dropsFormatPrice(d.typical_price_cents),
      _dropsFormatPct(d.pct_below),
      d.percentile === null || d.percentile === undefined
        ? '—'
        : `${Math.round(d.percentile)}th`,
      `${d.persisted_scrapes}×`,
    ];
    cells.forEach((c, i) => {
      const td = document.createElement('td');
      td.style.cssText =
        'padding:.4rem .5rem;' + (i >= 3 ? 'text-align:right;' : '');
      td.textContent = c;
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  return table;
}

function renderPriceDrops() {
  const container = document.getElementById('price-drops-container');
  if (!container) return;
  container.innerHTML = '';

  const blob = document.getElementById('DATA_PRICE_DROPS');
  if (!blob) return;
  const text = blob.textContent.trim();
  if (!text) {
    _dropsRenderEmpty(container, 'empty');
    return;
  }

  let data;
  try { data = JSON.parse(text); }
  catch (e) { console.error('Failed to parse DATA_PRICE_DROPS:', e); return; }

  if (data && data.insufficient_data) {
    _dropsRenderEmpty(container, data.insufficient_data, data.history_days);
    return;
  }
  const drops = (data && data.drops) || [];
  if (drops.length === 0) {
    _dropsRenderEmpty(container, 'empty');
    return;
  }
  container.appendChild(_dropsBuildTable(drops));
}
