// ───── State (single source of truth) ──────────────────────────────────────
const state = {
  route: null,            // first route from metadata.routes | 'both'
  calendarMonth: null,    // 'YYYY-MM' — currently displayed month
  selectedDate: null,     // 'YYYY-MM-DD' | null
  selectedFlight: null,   // { airline, dep_time } | null
  airlineFilter: new Set(), // empty Set = all airlines visible
  drilldownSort: 'price', // 'price' | 'time'
  airlineLeadTimeVisible: null,   // Set of visible airline names, null = initialise on first render
};

// ───── Chart registry — destroy before re-render to avoid leaks ────────────
const charts = {
  priceHistory: null,
  marketTrend: null,
  leadtime: null,
  dow: null,
  month: null,
  normProg: null,
  airlineLeadtime: null,
};

// Histogram and timeheat charts are keyed dynamically by route slug (e.g. 'CPH-AMS').
// They are stored as charts['histogram_CPH-AMS'] etc.

function destroyChart(slot) {
  if (charts[slot]) { charts[slot].destroy(); charts[slot] = null; }
}
