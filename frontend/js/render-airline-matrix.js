// ───── Airline seasonality matrix renderer ───────────────────────────────────
// Renders a buy-day × travel-day heatmap per airline and route.
// Reads DATA_AIRLINE_MATRIX JSON blob embedded in the page.

(function () {
  const CATEGORY_COLOR = {
    no:   '#e8e8e8',
    low:  '#fde4a3',
    med:  '#fdaa4f',
    high: '#c23c2a',
  };

  const CATEGORY_LABEL = {
    no:   'No',
    low:  'Low',
    med:  'Med',
    high: 'High',
  };

  const CATEGORY_DESCRIPTION = {
    no:   'No meaningful seasonality (≤1%)',
    low:  'Weak seasonality (1–5%)',
    med:  'Moderate seasonality (5–15%)',
    high: 'Strong seasonality (>15%)',
  };

  const TRAVEL_DAYS = ['Friday', 'Saturday', 'Sunday'];
  const BUY_DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

  function formatIndex(index) {
    const pct = (index * 100).toFixed(1);
    return index >= 0 ? `+${pct}%` : `${pct}%`;
  }

  function buildTooltip(buyDay, travelDay, cell) {
    if (!cell) return `Buy ${buyDay} → fly ${travelDay}\nNo data (<3 observations)`;
    const direction = cell.index > 0.01
      ? 'more expensive'
      : cell.index < -0.01
      ? 'cheaper'
      : 'about average';
    return [
      `Buy ${buyDay} → fly ${travelDay}`,
      `Relative index: ${formatIndex(cell.index)}`,
      `Observations: ${cell.n}`,
      `Interpretation: ${CATEGORY_DESCRIPTION[cell.category]} — ${direction} than average`,
    ].join('\n');
  }

  function buildTable(matrix) {
    const table = document.createElement('table');
    table.className = 'matrix-table';

    // Header row
    const thead = table.createTHead();
    const headerRow = thead.insertRow();
    const emptyTh = document.createElement('th');
    headerRow.appendChild(emptyTh);
    for (const travelDay of TRAVEL_DAYS) {
      const th = document.createElement('th');
      th.textContent = travelDay;
      headerRow.appendChild(th);
    }

    // Data rows (one per buy day)
    const tbody = table.createTBody();
    for (const buyDay of BUY_DAYS) {
      const row = tbody.insertRow();

      const labelTd = document.createElement('td');
      labelTd.className = 'matrix-buy-label';
      labelTd.textContent = buyDay;
      row.appendChild(labelTd);

      for (const travelDay of TRAVEL_DAYS) {
        const cell = matrix[travelDay] && matrix[travelDay][buyDay];
        const td = document.createElement('td');

        if (!cell) {
          td.className = 'matrix-cell matrix-cell--empty';
          td.textContent = '·';
        } else {
          td.className = 'matrix-cell';
          td.style.backgroundColor = CATEGORY_COLOR[cell.category];
          if (cell.category === 'high') td.style.color = '#fff';
          td.textContent = CATEGORY_LABEL[cell.category];
        }

        td.title = buildTooltip(buyDay, travelDay, cell || null);
        row.appendChild(td);
      }
    }

    return table;
  }

  function buildRouteBlock(route, airlines) {
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
      matrixDiv.appendChild(buildTable(entry.matrix));
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

  function renderAirlineMatrix() {
    const container = document.getElementById('airline-matrix-container');
    if (!container) return;

    const blob = document.getElementById('DATA_AIRLINE_MATRIX');
    if (!blob) return;

    const text = blob.textContent.trim();
    if (!text) return;

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
      container.appendChild(buildRouteBlock(route, data[route]));
    });
  }

  window.renderAirlineMatrix = renderAirlineMatrix;
})();
