// ───── Airline seasonality matrix renderer ───────────────────────────────────
// Renders a buy-day × travel-day heatmap per airline and route.
// Reads DATA_AIRLINE_MATRIX JSON blob embedded in the page.

const MATRIX_CATEGORY_COLOR = {
  no:              '#e8e8e8',  // gray (neutral)
  'cheap-low':     '#c8e6c9',  // light green
  'cheap-med':     '#66bb6a',  // medium green
  'cheap-high':    '#2e7d32',  // dark green
  'expensive-low':  '#ffccbc', // light coral
  'expensive-med':  '#ff7043', // medium orange-red
  'expensive-high': '#c62828', // dark red
};

const MATRIX_CATEGORY_LABEL = {
  no:              'No',
  'cheap-low':     'Low',
  'cheap-med':     'Med',
  'cheap-high':    'High',
  'expensive-low':  'Low',
  'expensive-med':  'Med',
  'expensive-high': 'High',
};

const MATRIX_CATEGORY_DESCRIPTION = {
  no:              'No meaningful seasonality (≤1%)',
  'cheap-low':     'Weak cheap season (1–5% below average)',
  'cheap-med':     'Moderate cheap season (5–15% below average)',
  'cheap-high':    'Strong cheap season (>15% below average)',
  'expensive-low':  'Weak expensive season (1–5% above average)',
  'expensive-med':  'Moderate expensive season (5–15% above average)',
  'expensive-high': 'Strong expensive season (>15% above average)',
};

const MATRIX_TRAVEL_DAYS = ['Friday', 'Saturday', 'Sunday'];
const MATRIX_BUY_DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

function _matrixFormatIndex(index) {
  const pct = (index * 100).toFixed(1);
  return index >= 0 ? `+${pct}%` : `${pct}%`;
}

function _matrixBuildTooltip(buyDay, travelDay, cell) {
  if (!cell) return `Buy ${buyDay} → fly ${travelDay}\nNo data (<3 observations)`;
  const direction = cell.index > 0.01
    ? 'more expensive'
    : cell.index < -0.01
    ? 'cheaper'
    : 'about average';
  return [
    `Buy ${buyDay} → fly ${travelDay}`,
    `Relative index: ${_matrixFormatIndex(cell.index)}`,
    `Observations: ${cell.n}`,
    `Interpretation: ${MATRIX_CATEGORY_DESCRIPTION[cell.category]} — ${direction} than average`,
  ].join('\n');
}

function _matrixBuildTable(matrix) {
  const table = document.createElement('table');
  table.className = 'matrix-table';

  // Axis label row: "Departure day →" spanning the 3 travel-day columns
  const thead = table.createTHead();
  const axisRow = thead.insertRow();
  const axisCorner = document.createElement('th');
  axisRow.appendChild(axisCorner);
  const axisTh = document.createElement('th');
  axisTh.colSpan = MATRIX_TRAVEL_DAYS.length;
  axisTh.textContent = 'Departure day →';
  axisTh.className = 'matrix-axis-label';
  axisRow.appendChild(axisTh);

  // Header row: corner = "Buy day ↓", then one TH per travel day
  const headerRow = thead.insertRow();
  const cornerTh = document.createElement('th');
  cornerTh.textContent = 'Buy day ↓';
  cornerTh.className = 'matrix-corner-label';
  headerRow.appendChild(cornerTh);
  for (const travelDay of MATRIX_TRAVEL_DAYS) {
    const th = document.createElement('th');
    th.textContent = travelDay;
    headerRow.appendChild(th);
  }

  // Data rows (one per buy day)
  const tbody = table.createTBody();
  for (const buyDay of MATRIX_BUY_DAYS) {
    const row = tbody.insertRow();

    const labelTd = document.createElement('td');
    labelTd.className = 'matrix-buy-label';
    labelTd.textContent = buyDay;
    row.appendChild(labelTd);

    for (const travelDay of MATRIX_TRAVEL_DAYS) {
      const cell = matrix[travelDay] && matrix[travelDay][buyDay];
      const td = document.createElement('td');

      if (!cell) {
        td.className = 'matrix-cell matrix-cell--empty';
        td.textContent = '·';
      } else {
        td.className = 'matrix-cell';
        td.style.backgroundColor = MATRIX_CATEGORY_COLOR[cell.category];
        if (cell.category === 'expensive-high') { td.style.color = '#fff'; }
        td.textContent = MATRIX_CATEGORY_LABEL[cell.category];
      }

      td.title = _matrixBuildTooltip(buyDay, travelDay, cell || null);
      row.appendChild(td);
    }
  }

  return table;
}

function _matrixBuildRouteBlock(route, airlines) {
  const block = document.createElement('div');
  block.className = 'matrix-route-block';

  const heading = document.createElement('h3');
  heading.textContent = route;
  block.appendChild(heading);

  if (!airlines || airlines.length === 0) {
    const empty = document.createElement('p');
    empty.textContent = 'No data for this route.';
    empty.style.color = '#888';
    block.appendChild(empty);
    return block;
  }

  // Radio selector
  const selectorGroup = document.createElement('div');
  selectorGroup.className = 'airline-selector-group';
  const groupName = `airline-matrix-${route.replace(/[^a-z0-9]/gi, '-')}`;

  const matrixDivs = [];

  airlines.forEach((entry, idx) => {
    // Radio + label
    const label = document.createElement('label');
    const radio = document.createElement('input');
    radio.type = 'radio';
    radio.name = groupName;
    radio.value = entry.airline;
    if (idx === 0) radio.checked = true;
    label.appendChild(radio);
    label.appendChild(document.createTextNode(entry.airline));
    selectorGroup.appendChild(label);

    // Matrix container
    const matrixDiv = document.createElement('div');
    matrixDiv.className = 'airline-matrix';
    matrixDiv.dataset.airline = entry.airline;
    matrixDiv.style.display = idx === 0 ? '' : 'none';
    matrixDiv.appendChild(_matrixBuildTable(entry.matrix));
    matrixDivs.push(matrixDiv);
  });

  // Wire radio change listeners
  selectorGroup.querySelectorAll('input[type="radio"]').forEach((radio) => {
    radio.addEventListener('change', () => {
      matrixDivs.forEach((div) => {
        div.style.display = div.dataset.airline === radio.value ? '' : 'none';
      });
    });
  });

  block.appendChild(selectorGroup);
  matrixDivs.forEach((div) => block.appendChild(div));

  return block;
}

function _showTooltip(text, cellElement) {
  const tooltip = document.getElementById('matrix-tooltip');
  if (!tooltip) return;

  tooltip.textContent = text;
  tooltip.classList.add('visible');

  // Position below the cell
  const rect = cellElement.getBoundingClientRect();
  const tooltipHeight = tooltip.offsetHeight;

  // Calculate position: centered horizontally on cell, below it
  const left = rect.left + (rect.width / 2) - (tooltip.offsetWidth / 2);
  const top = rect.bottom + 8; // 8px gap below cell

  tooltip.style.left = left + 'px';
  tooltip.style.top = top + 'px';
}

function _hideTooltip() {
  const tooltip = document.getElementById('matrix-tooltip');
  if (!tooltip) return;
  tooltip.classList.remove('visible');
}

function renderAirlineMatrix() {
  const container = document.getElementById('airline-matrix-container');
  if (!container) return;

  const blob = document.getElementById('DATA_AIRLINE_MATRIX');
  if (!blob) return;

  const text = blob.textContent.trim();
  if (!text) return;

  // ─── Create tooltip element ───────────────────────────────────────────────
  let tooltip = document.getElementById('matrix-tooltip');
  if (!tooltip) {
    tooltip = document.createElement('div');
    tooltip.id = 'matrix-tooltip';
    document.body.appendChild(tooltip);
  }
  // ───────────────────────────────────────────────────────────────────────────

  let data;
  try {
    data = JSON.parse(text);
  } catch (e) {
    console.error('Failed to parse DATA_AIRLINE_MATRIX:', e);
    return;
  }

  if (!data || typeof data !== 'object') return;

  const routes = Object.keys(data).sort();
  if (routes.length === 0) return;

  routes.forEach((route) => {
    container.appendChild(_matrixBuildRouteBlock(route, data[route]));
  });
}
