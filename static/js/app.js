let map, routeLayer, markerLayer, circleLayer, currentTripId = null;

const formatNumber = (v, d = 2) => {
  const n = Number(v ?? 0);
  return Number.isFinite(n) ? n.toFixed(d) : '0.00';
};

const formatDate = v => !v ? '—' : new Date(v).toLocaleString();

const el = html => {
  const t = document.createElement('template');
  t.innerHTML = html.trim();
  return t.content.firstChild;
};

function ensureMap() {
  if (map) return;

  map = L.map('map').setView([45.553, -94.154], 13);

  L.tileLayer(
    'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
    { attribution: '&copy; OpenStreetMap contributors' }
  ).addTo(map);

  routeLayer = L.layerGroup().addTo(map);
  markerLayer = L.layerGroup().addTo(map);
  circleLayer = L.layerGroup().addTo(map);
}

async function fetchJSON(url, options = {}) {
  const res = await fetch(url, options);

  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `Request failed: ${res.status}`);
  }

  return res.json();
}

function renderSummary(summary) {
  const c = document.getElementById('summaryCards');
  c.innerHTML = '';

  [
    ['Users', summary.users],
    ['Devices', summary.devices],
    ['Trips', summary.trips],
    ['Total Distance (km)', formatNumber(summary.total_distance_km)]
  ].forEach(([label, value]) => {
    c.appendChild(
      el(`
        <div class="card">
          <div class="label">${label}</div>
          <div class="value">${value}</div>
        </div>
      `)
    );
  });
}

function renderSimpleList(targetId, items, formatter) {
  const c = document.getElementById(targetId);
  c.innerHTML = '';
  c.className = 'list';

  items.forEach(item => c.appendChild(formatter(item)));
}

async function loadDashboard() {
  const data = await fetchJSON('/api/dashboard');

  renderSummary(data.summary);

  renderSimpleList(
    'topGeofences',
    data.top_geofences,
    item => el(`
      <div class="list-item">
        <strong>${item.geofence_name}</strong><br />
        <span class="muted">${item.crossing_count} crossing(s)</span>
      </div>
    `)
  );

  renderSimpleList(
    'poiBreakdown',
    data.poi_breakdown,
    item => el(`
      <div class="list-item">
        <strong>${item.category}</strong><br />
        <span class="muted">${item.poi_count} POI(s)</span>
      </div>
    `)
  );
}

function buildTripsUrl() {
  const params = new URLSearchParams();

  [
    ['user_id', filterUserId.value],
    ['device_id', filterDeviceId.value],
    ['tag', filterTag.value.trim()],
    ['min_distance', filterMinDistance.value],
    ['max_distance', filterMaxDistance.value]
  ].forEach(([k, v]) => {
    if (v) params.set(k, v);
  });

  return '/api/trips' + (params.toString() ? `?${params.toString()}` : '');
}

async function loadTrips() {
  const trips = await fetchJSON(buildTripsUrl());

  const list = document.getElementById('tripList');
  list.innerHTML = '';

  if (!trips.length) {
    list.innerHTML = '<div class="empty-state">No trips matched those filters.</div>';
    return;
  }

  trips.forEach(trip => {
    const item = el(`
      <div class="trip-item ${trip.trip_id === currentTripId ? 'active' : ''}" data-trip-id="${trip.trip_id}">
        <strong>Trip #${trip.trip_id}</strong>

        <div class="meta">
          ${trip.full_name}<br />
          ${trip.device_name} (${trip.device_type})<br />
          ${formatDate(trip.started_at)} → ${formatDate(trip.ended_at)}
        </div>

        <div class="meta">
          Distance: ${formatNumber(trip.total_distance_km, 3)} km ·
          Avg Speed: ${formatNumber(trip.avg_speed_kmh)} km/h ·
          Stops: ${trip.stop_count}
        </div>

        <div class="tags">
          Tags: ${trip.tags || 'none'}
        </div>
      </div>
    `);

    item.addEventListener('click', () => selectTrip(trip.trip_id));
    list.appendChild(item);
  });

  if (!currentTripId && trips.length) {
    await selectTrip(trips[0].trip_id);
  }
}

function clearMapLayers() {
  routeLayer.clearLayers();
  markerLayer.clearLayers();
  circleLayer.clearLayers();
}

function renderTripDetail(detail) {
  const trip = detail.trip;

  detailChips.innerHTML = '';

  [
    `Trip #${trip.trip_id}`,
    `${trip.point_count} stored points`,
    `${detail.computed_stops.length} computed stops`,
    trip.tags ? `Tags: ${trip.tags}` : 'Tags: none'
  ].forEach(text => {
    detailChips.appendChild(el(`<span class="chip">${text}</span>`));
  });

  mapMeta.textContent =
    `${trip.full_name} · ${trip.device_name} · ${formatDate(trip.started_at)} to ${formatDate(trip.ended_at)}`;

  const stopItems = detail.stops.length
    ? `<ul>${detail.stops.map(s =>
        `<li>${formatDate(s.started_at)} → ${formatDate(s.ended_at)} (${s.duration_seconds}s)</li>`
      ).join('')}</ul>`
    : '<p class="muted">No stored stop events.</p>';

  const geofenceItems = detail.geofences.length
    ? `<ul>${detail.geofences.map(f =>
        `<li>${f.geofence_name}: ${formatDate(f.entered_at)} → ${formatDate(f.exited_at)}</li>`
      ).join('')}</ul>`
    : '<p class="muted">No geofence crossings recorded.</p>';

  tripDetail.className = 'trip-detail';

  tripDetail.innerHTML = `
    <div class="trip-detail-grid">
      <div class="detail-section">
        <h3>Stored Summary</h3>
        <p>Total distance: <strong>${formatNumber(trip.total_distance_km, 3)} km</strong></p>
        <p>Duration: <strong>${formatNumber(trip.duration_minutes)} min</strong></p>
        <p>Average speed: <strong>${formatNumber(trip.avg_speed_kmh)} km/h</strong></p>
        <p>Stops: <strong>${trip.stop_count}</strong></p>
      </div>

      <div class="detail-section">
        <h3>Computed Summary</h3>
        <p>Total distance: <strong>${formatNumber(trip.computed_metrics.total_distance_km, 3)} km</strong></p>
        <p>Duration: <strong>${formatNumber(trip.computed_metrics.duration_minutes)} min</strong></p>
        <p>Average speed: <strong>${formatNumber(trip.computed_metrics.avg_speed_kmh)} km/h</strong></p>
        <p>Points: <strong>${trip.computed_metrics.point_count}</strong></p>
      </div>

      <div class="detail-section">
        <h3>Route Health</h3>
        <p>Status: <strong>${trip.status}</strong></p>
        <p>Device: <strong>${trip.device_type}</strong></p>
        <p>User: <strong>${trip.full_name}</strong></p>
      </div>
    </div>

    <div class="detail-section">
      <h3>Stop Events</h3>
      ${stopItems}
    </div>

    <div class="detail-section">
      <h3>Geofence Crossings</h3>
      ${geofenceItems}
    </div>
  `;
}

async function renderReferenceLayers() {
  const data = await fetchJSON('/api/reference');

  data.pois.forEach(poi => {
    const marker = L.circleMarker(
      [poi.latitude, poi.longitude],
      { radius: 6 }
    );

    marker.bindPopup(`<strong>${poi.poi_name}</strong><br />${poi.category}`);
    markerLayer.addLayer(marker);
  });

  data.geofences.forEach(fence => {
    const circle = L.circle(
      [fence.center_lat, fence.center_lon],
      {
        radius: fence.radius_m,
        weight: 1.5,
        fillOpacity: .06
      }
    );

    circle.bindPopup(`<strong>${fence.geofence_name}</strong><br />Radius: ${fence.radius_m}m`);
    circleLayer.addLayer(circle);
  });
}

async function selectTrip(tripId) {
  currentTripId = tripId;

  [...document.querySelectorAll('.trip-item')].forEach(node => {
    node.classList.toggle(
      'active',
      Number(node.dataset.tripId) === tripId
    );
  });

  const detail = await fetchJSON(`/api/trips/${tripId}`);

  renderTripDetail(detail);

  ensureMap();
  clearMapLayers();

  await renderReferenceLayers();

  const latlngs = detail.points.map(p => [p.latitude, p.longitude]);

  if (latlngs.length) {
    const polyline = L.polyline(latlngs, { weight: 4 }).addTo(routeLayer);

    map.fitBounds(polyline.getBounds(), {
      padding: [30, 30]
    });

    const first = detail.points[0];
    const last = detail.points[detail.points.length - 1];

    L.marker([first.latitude, first.longitude])
      .bindPopup('Trip start')
      .addTo(routeLayer);

    L.marker([last.latitude, last.longitude])
      .bindPopup('Trip end')
      .addTo(routeLayer);
  }

  detail.stops.forEach(stop => {
    L.circleMarker(
      [stop.latitude, stop.longitude],
      { radius: 8 }
    )
      .bindPopup(`<strong>Stop event</strong><br />${formatDate(stop.started_at)}<br />${stop.duration_seconds}s`)
      .addTo(routeLayer);
  });
}

function clearFilters() {
  [
    'filterUserId',
    'filterDeviceId',
    'filterTag',
    'filterMinDistance',
    'filterMaxDistance'
  ].forEach(id => {
    document.getElementById(id).value = '';
  });
}

refreshDashboardBtn.addEventListener('click', loadDashboard);
loadTripsBtn.addEventListener('click', loadTrips);
applyFiltersBtn.addEventListener('click', loadTrips);

clearFiltersBtn.addEventListener('click', async () => {
  clearFilters();
  await loadTrips();
});

// =========================
// CRUD FORM WITH COORDINATE VALIDATION
// =========================

function toIsoFromLocal(value) {
  return value ? new Date(value).toISOString() : null;
}

function toLocalInputValue(value) {
  if (!value) return '';

  const d = new Date(value);
  const offset = d.getTimezoneOffset();
  const local = new Date(d.getTime() - offset * 60000);

  return local.toISOString().slice(0, 16);
}

function showCrudMessage(message, isError = false) {
  const box = document.getElementById('crudMessage');

  if (!box) return;

  box.textContent = message;
  box.style.borderLeft = isError
    ? '4px solid #b91c1c'
    : '4px solid #15803d';
}

function addCoordinateRow(point = {}) {
  const rows = document.getElementById('coordinateRows');

  if (!rows) return;

  const row = el(`
    <div class="coordinate-row">
      <label>
        Latitude
        <input class="coord-lat" type="number" step="0.000001" placeholder="45.553000" value="${point.latitude ?? ''}" />
      </label>

      <label>
        Longitude
        <input class="coord-lon" type="number" step="0.000001" placeholder="-94.154000" value="${point.longitude ?? ''}" />
      </label>

      <label>
        Recorded At
        <input class="coord-time" type="datetime-local" value="${toLocalInputValue(point.recorded_at)}" />
      </label>

      <button type="button" class="remove-coordinate secondary">Remove</button>
    </div>
  `);

  row.querySelector('.remove-coordinate')
    .addEventListener('click', () => row.remove());

  rows.appendChild(row);
}

function validateCoordinate(lat, lon, rowNumber) {
  const latNum = Number(lat);
  const lonNum = Number(lon);

  if (!Number.isFinite(latNum) || !Number.isFinite(lonNum)) {
    return `Coordinate row ${rowNumber}: latitude and longitude must be numbers.`;
  }

  if (latNum < -90 || latNum > 90) {
    return `Coordinate row ${rowNumber}: latitude must be between -90 and 90.`;
  }

  if (lonNum < -180 || lonNum > 180) {
    return `Coordinate row ${rowNumber}: longitude must be between -180 and 180.`;
  }

  return null;
}

function collectTripFormPayload() {
  const startedAt = toIsoFromLocal(crudStartedAt.value);
  const endedAt = toIsoFromLocal(crudEndedAt.value);

  if (!crudUserId.value || !crudDeviceId.value || !startedAt) {
    throw new Error('User ID, Device ID, and Start Date are required.');
  }

  if (endedAt && new Date(endedAt) < new Date(startedAt)) {
    throw new Error('End Date cannot be before Start Date.');
  }

  const points = [...document.querySelectorAll('.coordinate-row')].map((row, index) => {
    const latitude = row.querySelector('.coord-lat').value;
    const longitude = row.querySelector('.coord-lon').value;
    const recordedAt =
      toIsoFromLocal(row.querySelector('.coord-time').value) || startedAt;

    const error = validateCoordinate(latitude, longitude, index + 1);

    if (error) {
      throw new Error(error);
    }

    return {
      latitude: Number(latitude),
      longitude: Number(longitude),
      recorded_at: recordedAt
    };
  });

  if (points.length < 2) {
    throw new Error('Please enter at least two valid coordinate rows.');
  }

  return {
    user_id: Number(crudUserId.value),
    device_id: Number(crudDeviceId.value),
    started_at: startedAt,
    ended_at: endedAt,
    points
  };
}

async function insertTripFromForm() {
  try {
    const payload = collectTripFormPayload();

    const result = await fetchJSON('/api/trips', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(payload)
    });

    currentTripId = result.trip.trip_id;

    showCrudMessage(
      `Inserted Trip #${currentTripId} with ${payload.points.length} coordinates.`
    );

    await loadDashboard();
    await loadTrips();
    await selectTrip(currentTripId);

  } catch (err) {
    showCrudMessage(err.message, true);
  }
}

async function updateTripFromForm() {
  if (!currentTripId) {
    showCrudMessage('Select a trip first before updating.', true);
    return;
  }

  try {
    const payload = collectTripFormPayload();

    const result = await fetchJSON(`/api/trips/${currentTripId}`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(payload)
    });

    showCrudMessage(`Updated Trip #${result.trip.trip_id}.`);

    await loadDashboard();
    await loadTrips();
    await selectTrip(result.trip.trip_id);

  } catch (err) {
    showCrudMessage(err.message, true);
  }
}

async function deleteSelectedTrip() {
  if (!currentTripId) {
    showCrudMessage('Select a trip first before deleting.', true);
    return;
  }

  if (!confirm(`Delete Trip #${currentTripId}? This deletes only the selected trip, not later trips.`)) {
    return;
  }

  try {
    const deletedId = currentTripId;

    const result = await fetchJSON(`/api/trips/${deletedId}`, {
      method: 'DELETE'
    });

    currentTripId = null;

    showCrudMessage(result.message || `Deleted Trip #${deletedId}.`);

    await loadDashboard();
    await loadTrips();

  } catch (err) {
    showCrudMessage(err.message, true);
  }
}

async function fillCrudFormFromSelectedTrip() {
  if (!currentTripId) return;

  const detail = await fetchJSON(`/api/trips/${currentTripId}`);
  const trip = detail.trip;

  crudUserId.value = trip.user_id;
  crudDeviceId.value = trip.device_id;
  crudStartedAt.value = toLocalInputValue(trip.started_at);
  crudEndedAt.value = toLocalInputValue(trip.ended_at);

  coordinateRows.innerHTML = '';

  detail.points.forEach(point => addCoordinateRow(point));

  if (detail.points.length < 2) {
    addCoordinateRow();
    addCoordinateRow();
  }
}

const originalSelectTrip = selectTrip;

selectTrip = async function (tripId) {
  await originalSelectTrip(tripId);
  await fillCrudFormFromSelectedTrip();
};

async function runTransactionDemo(action) {
  const out = document.getElementById('transactionOutput');

  try {
    const result = await fetchJSON('/api/transaction-demo', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ action })
    });

    out.textContent =
      `${result.message}\n\nSQL demo:\n${(result.sql || []).join('\n')}`;

    await loadDashboard();
    await loadTrips();

  } catch (err) {
    out.textContent = `Transaction demo failed: ${err.message}`;
  }
}

async function runExplainBeforeAfter() {
  const out = document.getElementById('explainOutput');

  out.textContent = 'Running EXPLAIN ANALYZE before and after index...';

  try {
    const result = await fetchJSON('/api/explain-before-after');

    out.textContent =
      `Query:\n${result.query}\n\n` +
      `Index Added:\n${result.index_added}\n\n` +
      `BEFORE INDEX:\n${result.before_index.join('\n')}\n\n` +
      `AFTER INDEX:\n${result.after_index.join('\n')}\n\n` +
      `${result.note}`;

  } catch (err) {
    out.textContent = `EXPLAIN failed: ${err.message}`;
  }
}

function initializeCrudDefaults() {
  if (!document.getElementById('coordinateRows')) return;

  const now = new Date();
  const later = new Date(now.getTime() + 10 * 60000);

  crudStartedAt.value = toLocalInputValue(now.toISOString());
  crudEndedAt.value = toLocalInputValue(later.toISOString());

  addCoordinateRow({
    latitude: 45.553000,
    longitude: -94.154000,
    recorded_at: now.toISOString()
  });

  addCoordinateRow({
    latitude: 45.558000,
    longitude: -94.148000,
    recorded_at: later.toISOString()
  });
}

addCoordinateBtn?.addEventListener('click', () => addCoordinateRow());

insertTripBtn?.addEventListener('click', insertTripFromForm);
updateTripBtn?.addEventListener('click', updateTripFromForm);
deleteTripBtn?.addEventListener('click', deleteSelectedTrip);

commitBtn?.addEventListener('click', () => runTransactionDemo('commit'));
rollbackBtn?.addEventListener('click', () => runTransactionDemo('rollback'));
savepointBtn?.addEventListener('click', () => runTransactionDemo('savepoint'));

explainBtn?.addEventListener('click', runExplainBeforeAfter);

initializeCrudDefaults();

ensureMap();

Promise.all([
  loadDashboard(),
  loadTrips()
]).catch(err => {
  console.error(err);
  tripDetail.textContent = `Error loading dashboard: ${err.message}`;
});