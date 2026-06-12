// ───── Data (populated once on boot) ───────────────────────────────────────
let DATA = null;

function readJsonBlob(id) {
  const el = $(id);
  if (!el) return null;
  const text = el.textContent.trim();
  if (!text) return null;
  try { return JSON.parse(text); }
  catch (e) { console.error('Failed to parse', id, e); return null; }
}

function _showFatalBanner(msg) {
  const el = document.getElementById('data-load-error');
  if (el) {
    el.textContent = msg;
    el.style.display = 'block';
  } else {
    // Fallback: inject a banner at the top of the body
    const div = document.createElement('div');
    div.style.cssText =
      'position:fixed;inset:0;z-index:9999;background:#fff3cd;color:#856404;' +
      'padding:2rem;font-family:sans-serif;font-size:1.1rem;';
    div.textContent = msg;
    document.body.prepend(div);
  }
}

async function loadData() {
  // Try inline blobs first (generated with --inline-data, or for unit tests).
  const inlineMetadata = readJsonBlob('DATA_METADATA');
  if (inlineMetadata !== null) {
    return {
      metadata: inlineMetadata,
      calendar: readJsonBlob('DATA_CALENDAR') || {},
      flights: readJsonBlob('DATA_FLIGHTS') || {},
      analysis: readJsonBlob('DATA_ANALYSIS') || {},
      summary: readJsonBlob('DATA_SUMMARY') || {},
      health: readJsonBlob('DATA_HEALTH') || {},
      price_percentile: readJsonBlob('DATA_PRICE_PERCENTILE') || {},
      momentum: readJsonBlob('DATA_MOMENTUM') || {},
      volatility: readJsonBlob('DATA_VOLATILITY') || {},
      price_drops: readJsonBlob('DATA_PRICE_DROPS') || {},
    };
  }

  // No inline data — fetch data.json from the same directory as the page.
  try {
    const response = await fetch('data.json');
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const d = await response.json();
    return {
      metadata: d.metadata || {},
      calendar: d.calendar || {},
      flights: d.flights || {},
      analysis: d.analysis || {},
      summary: d.summary || {},
      health: d.health || {},
      price_percentile: d.price_percentile || {},
      momentum: d.momentum || {},
      volatility: d.volatility || {},
      price_drops: d.price_drops || {},
    };
  } catch (err) {
    console.error('Failed to load data.json:', err);
    _showFatalBanner(
      'Dashboard data could not be loaded. ' +
      'Open this page via a local web server (e.g. python3 -m http.server), ' +
      'or regenerate with --inline-data for a fully self-contained file.'
    );
    return {
      metadata: {},
      calendar: {},
      flights: {},
      analysis: {},
      summary: {},
      health: {},
    };
  }
}
