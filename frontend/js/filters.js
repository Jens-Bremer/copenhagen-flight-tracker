/** Active routes derived from state.route. */
function activeRoutes() {
  if (state.route === 'both') return DATA.metadata.routes || [];
  if (state.route) return [state.route];
  return DATA.metadata.routes || [];
}

/** True if a row's airline survives the current filter. Empty filter = all pass. */
function airlinePasses(airline) {
  return state.airlineFilter.size === 0 || state.airlineFilter.has(airline);
}

// ───── Filter wiring ───────────────────────────────────────────────────────
function wireFilters() {
  // CHANGE (UX): inject a small uppercase label before each group of chips
  // so the role is obvious without a tooltip. Cleared each render so we
  // never accumulate duplicates.
  function ensureLabel(container, text) {
    const existing = container.previousElementSibling;
    if (existing && existing.classList && existing.classList.contains('filters__label')) {
      existing.textContent = text;
      return;
    }
    const label = document.createElement('span');
    label.className = 'filters__label';
    label.textContent = text;
    container.parentNode.insertBefore(label, container);
  }

  // Route toggle — built dynamically from metadata.routes
  const allRoutes = DATA.metadata.routes || [];
  const routeOptions = allRoutes.length > 1
    ? [...allRoutes, 'both']
    : allRoutes;

  const routeContainer = $('route-toggle');
  routeContainer.innerHTML = '';
  ensureLabel(routeContainer, 'Route');
  routeOptions.forEach((r) => {
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'filter-chip' + (state.route === r ? ' is-active' : '');
    chip.textContent = r === 'both' ? 'Both' : r;
    chip.dataset.route = r;
    chip.addEventListener('click', () => {
      state.route = r;
      state.selectedDate = null;
      state.selectedFlight = null;
      Array.from(routeContainer.children).forEach((c) => {
        c.classList.toggle('is-active', c.dataset.route === r);
      });
      renderAll();
    });
    routeContainer.appendChild(chip);
  });

  // Airline filter — chips for every airline in metadata
  const airlineContainer = $('airline-filter');
  airlineContainer.innerHTML = '';
  ensureLabel(airlineContainer, 'Airline');
  const airlines = (DATA.metadata.airlines || []).slice().sort();
  airlines.forEach((a) => {
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'filter-chip';
    chip.style.borderLeft = `8px solid ${airlineColor(a)}`;
    chip.textContent = a;
    chip.dataset.airline = a;
    chip.addEventListener('click', () => {
      if (state.airlineFilter.has(a)) state.airlineFilter.delete(a);
      else state.airlineFilter.add(a);
      chip.classList.toggle('is-active', state.airlineFilter.has(a));
      renderAll();
    });
    airlineContainer.appendChild(chip);
  });
}
