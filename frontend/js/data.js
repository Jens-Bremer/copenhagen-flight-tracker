// ───── Data (populated once on boot) ───────────────────────────────────────
let DATA = null;

function readJsonBlob(id) {
  const el = $(id);
  if (!el) return null;
  try { return JSON.parse(el.textContent); }
  catch (e) { console.error('Failed to parse', id, e); return null; }
}

function loadData() {
  return {
    metadata: readJsonBlob('DATA_METADATA') || {},
    calendar: readJsonBlob('DATA_CALENDAR') || {},
    flights: readJsonBlob('DATA_FLIGHTS') || {},
    analysis: readJsonBlob('DATA_ANALYSIS') || {},
    summary: readJsonBlob('DATA_SUMMARY') || {},
  };
}
