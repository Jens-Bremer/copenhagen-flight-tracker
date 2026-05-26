// ───── Airline brand colours (locked) ──────────────────────────────────────
const AIRLINE_COLORS = {
  'KLM':                    '#00A1DE',
  'Norwegian':              '#D4001E',
  'easyJet':                '#FF6600',
  'Scandinavian Airlines':  '#003087',
  'SAS':                    '#003087',
  'Ryanair':                '#F1C40F',
  'Finnair':                '#00386F',
};
const AIRLINE_OUTLINE = new Set();

const _DOW_LABELS_SHORT = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

const REQUIRED_DOM_IDS = [
  'header-range', 'header-generated', 'footer-generated',
  'route-toggle', 'airline-filter',
  'hero-best-time', 'hero-market', 'hero-book-when',
  'cal-prev', 'cal-month-label', 'cal-next',
  'calendar', 'drilldown-panel', 'drilldown-title', 'drilldown-sort', 'drilldown',
  'price-history-wrap', 'verdict-card', 'price-history-chart',
  'leadtime-chart', 'sweet-spot-headline',
  'histograms-container',
  'weekend-pairs',
  'dow-chart', 'month-chart',
  'airline-boxplots-container',
  'timeheat-container',
  'normprog-chart',
];

// ───── Route palette — index by position in DATA.metadata.routes ────────────
// Index 0 (CPH-AMS) stays red, index 1 (AMS-CPH) stays blue for backward compat.
const ROUTE_PALETTE = [
  '#c0392b', // red    (CPH-AMS index 0)
  '#2980b9', // blue   (AMS-CPH index 1)
  '#16a085', // teal
  '#8e44ad', // purple
  '#f39c12', // orange
  '#27ae60', // green
  '#d35400', // dark orange
  '#2c3e50', // dark slate
];
