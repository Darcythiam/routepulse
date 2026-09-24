let map, routeLayer, markerLayer, circleLayer, currentTripId = null;
let liveSocket = null, livePolyline = null, liveMarker = null, reconnectTimer = null;
let knownPointIds = new Set();

const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, ch => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
})[ch]);

const formatNumber = (v, d = 2) => {
  const n = Number(v ?? 0);
  return Number.isFinite(n) ? n.toFixed(d) : '0.00';
};

const formatDate = v =>
  !v ? '—' : new Date(v).toLocaleString();

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
    {
      attribution: '&copy; OpenStreetMap contributors'
    }
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
        <strong>${escapeHtml(item.geofence_name)}</strong><br />
        <span class="muted">
          ${item.crossing_count} crossing(s)
        </span>
      </div>
    `)
  );

  renderSimpleList(
    'poiBreakdown',
    data.poi_breakdown,
    item => el(`
      <div class="list-item">
        <strong>${escapeHtml(item.category)}</strong><br />
        <span class="muted">
          ${item.poi_count} POI(s)
        </span>
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

  return '/api/trips' +
    (params.toString() ? `?${params.toString()}` : '');
}

async function loadTrips() {
  const trips = await fetchJSON(buildTripsUrl());

  const list = document.getElementById('tripList');
  list.innerHTML = '';

  if (!trips.length) {
    list.innerHTML =
      '<div class="empty-state">No trips found.</div>';
    return;
  }

  trips.forEach(trip => {
    const item = el(`
      <div class="trip-item
        ${trip.trip_id === currentTripId ? 'active' : ''}"
        data-trip-id="${trip.trip_id}">

        <strong>Trip #${trip.trip_id}</strong>

        <div class="meta">
          ${escapeHtml(trip.full_name)}<br />
          ${escapeHtml(trip.device_name)}
          (${escapeHtml(trip.device_type)})<br />

          ${formatDate(trip.started_at)}
          →
          ${formatDate(trip.ended_at)}
        </div>

        <div class="meta">
          Distance:
          ${formatNumber(trip.total_distance_km, 3)} km
          · Avg Speed:
          ${formatNumber(trip.avg_speed_kmh)} km/h
          · Stops:
          ${trip.stop_count}
        </div>

      </div>
    `);

    item.addEventListener(
      'click',
      () => selectTrip(trip.trip_id)
    );

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
    `${detail.computed_stops.length} computed stops`
  ].forEach(text => {
    detailChips.appendChild(
      el(`<span class="chip">${text}</span>`)
    );
  });

  mapMeta.textContent =
    `${trip.full_name} · ${trip.device_name}`;

  tripDetail.className = 'trip-detail';

  tripDetail.innerHTML = `
    <div class="trip-detail-grid">

      <div class="detail-section">
        <h3>Stored Summary</h3>

        <p>
          Distance:
          <strong>
            ${formatNumber(trip.total_distance_km, 3)} km
          </strong>
        </p>

        <p>
          Duration:
          <strong>
            ${formatNumber(trip.duration_minutes)} min
          </strong>
        </p>

        <p>
          Avg Speed:
          <strong>
            ${formatNumber(trip.avg_speed_kmh)} km/h
          </strong>
        </p>

        <p>
          Stops:
          <strong>${trip.stop_count}</strong>
        </p>
      </div>

      <div class="detail-section">
        <h3>Status</h3>

        <p>
          <strong>${escapeHtml(trip.status)}</strong>
        </p>

        <p>
          User:
          <strong>${escapeHtml(trip.full_name)}</strong>
        </p>

        <p>
          Device:
          <strong>${escapeHtml(trip.device_name)}</strong>
        </p>
      </div>

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

    marker.bindPopup(
      `<strong>${escapeHtml(poi.poi_name)}</strong><br />${escapeHtml(poi.category)}`
    );

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

    circle.bindPopup(`
      <strong>${escapeHtml(fence.geofence_name)}</strong><br />
      Radius: ${fence.radius_m}m
    `);

    circleLayer.addLayer(circle);
  });
}

async function selectTrip(tripId) {
  if (liveSocket) {
    const previous = liveSocket;
    liveSocket = null;
    previous.close();
  }
  if (reconnectTimer) clearTimeout(reconnectTimer);
  currentTripId = tripId;

  [...document.querySelectorAll('.trip-item')]
    .forEach(node => {
      node.classList.toggle(
        'active',
        Number(node.dataset.tripId) === tripId
      );
    });

  const detail = await fetchJSON(
    `/api/trips/${tripId}`
  );

  renderTripDetail(detail);

  ensureMap();
  clearMapLayers();
  liveMarker = null;

  await renderReferenceLayers();

  const latlngs = detail.points.map(p => [
    p.latitude,
    p.longitude
  ]);

  knownPointIds = new Set(detail.points.map(point => point.point_id));
  livePolyline = L.polyline(latlngs, { weight: 4 }).addTo(routeLayer);
  if (latlngs.length) map.fitBounds(livePolyline.getBounds(), { padding: [30, 30] });
  detail.stops.forEach(stop => {
    L.circleMarker([stop.latitude, stop.longitude], { radius: 8, color: '#b6f09c' })
      .bindPopup(`Stop: ${Math.round(stop.duration_seconds / 60)} min`)
      .addTo(markerLayer);
  });
  if (detail.trip.status === 'in_progress') connectTripSocket(tripId);
}

function connectTripSocket(tripId) {
  if (tripId !== currentTripId) return;
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const socket = new WebSocket(`${protocol}//${location.host}/ws/trips/${tripId}`);
  liveSocket = socket;
  let messageQueue = Promise.resolve();
  socket.onmessage = event => {
    messageQueue = messageQueue.then(() => handleMessage(JSON.parse(event.data)))
      .catch(err => console.error('Live position update failed:', err));
  };
  async function handleMessage(data) {
    if (tripId !== currentTripId) return;
    if (data.type === 'subscribed') {
      // Refresh after subscribing to cover the gap between initial GET and socket setup.
      const snapshot = await fetchJSON(`/api/trips/${tripId}`);
      if (tripId !== currentTripId || socket !== liveSocket) return;
      knownPointIds = new Set(snapshot.points.map(point => point.point_id));
      livePolyline.setLatLngs(snapshot.points.map(point => [point.latitude, point.longitude]));
      renderTripDetail(snapshot);
    }
    if (data.type === 'position' && !knownPointIds.has(data.point_id)) {
      knownPointIds.add(data.point_id);
      const position = [data.latitude, data.longitude];
      livePolyline.addLatLng(position);
      if (liveMarker) liveMarker.setLatLng(position);
      else liveMarker = L.circleMarker(position, { radius: 8, color: '#7cc7ff' }).addTo(markerLayer);
      map.panTo(position);
    }
    if (data.type === 'completed') {
      await selectTrip(tripId);
      await loadTrips();
    }
  }
  socket.onclose = () => {
    if (tripId === currentTripId && socket === liveSocket) {
      reconnectTimer = setTimeout(() => connectTripSocket(tripId), 2000);
    }
  };
}

function toIsoFromLocal(value) {
  return value
    ? new Date(value).toISOString()
    : null;
}

function showCrudMessage(message, isError = false) {
  const box =
    document.getElementById('crudMessage');

  if (!box) return;

  box.textContent = message;

  box.style.borderLeft = isError
    ? '4px solid #b91c1c'
    : '4px solid #15803d';
}

function addCoordinateRow(point = {}) {
  const rows =
    document.getElementById('coordinateRows');

  const row = el(`
    <div class="coordinate-row">

      <label>
        Latitude
        <input
          class="coord-lat"
          type="number"
          step="0.000001"
          value="${point.latitude ?? ''}"
        />
      </label>

      <label>
        Longitude
        <input
          class="coord-lon"
          type="number"
          step="0.000001"
          value="${point.longitude ?? ''}"
        />
      </label>

      <label>
        Recorded At
        <input
          class="coord-time"
          type="datetime-local"
        />
      </label>

      <button
        type="button"
        class="remove-coordinate secondary">

        Remove

      </button>

    </div>
  `);

  row.querySelector('.remove-coordinate')
    .addEventListener('click', () => row.remove());

  rows.appendChild(row);
}

function validateCoordinate(lat, lon) {
  if (lat < -90 || lat > 90) {
    return false;
  }

  if (lon < -180 || lon > 180) {
    return false;
  }

  return true;
}

function collectTripFormPayload() {
  const startedAt =
    toIsoFromLocal(crudStartedAt.value);

  const endedAt =
    toIsoFromLocal(crudEndedAt.value);

  const points = [];

  [...document.querySelectorAll('.coordinate-row')]
    .forEach(row => {

      const latitude = Number(
        row.querySelector('.coord-lat').value
      );

      const longitude = Number(
        row.querySelector('.coord-lon').value
      );

      const recordedAt =
        toIsoFromLocal(
          row.querySelector('.coord-time').value
        ) || startedAt;

      if (!validateCoordinate(latitude, longitude)) {
        throw new Error(
          'Coordinates are not valid.'
        );
      }

      points.push({
        latitude,
        longitude,
        recorded_at: recordedAt
      });
    });

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
    const payload =
      collectTripFormPayload();

    const result = await fetchJSON(
      '/api/trips',
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(payload)
      }
    );

    currentTripId = result.trip.trip_id;

    showCrudMessage(
      `Trip #${currentTripId} inserted successfully.`
    );

    await loadDashboard();
    await loadTrips();

  } catch (err) {
    showCrudMessage(err.message, true);
  }
}

async function updateTripFromForm() {
  if (!currentTripId) {
    showCrudMessage(
      'Select a trip first.',
      true
    );
    return;
  }

  try {
    const payload =
      collectTripFormPayload();

    const result = await fetchJSON(
      `/api/trips/${currentTripId}`,
      {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(payload)
      }
    );

    showCrudMessage(
      `Trip #${result.trip.trip_id} updated successfully.`
    );

    await loadDashboard();
    await loadTrips();

  } catch (err) {
    showCrudMessage(err.message, true);
  }
}

async function deleteSelectedTrip() {
  if (!currentTripId) {
    showCrudMessage(
      'Select a trip first.',
      true
    );
    return;
  }

  if (!confirm(
    `Delete Trip #${currentTripId}?`
  )) {
    return;
  }

  try {
    await fetchJSON(
      `/api/trips/${currentTripId}`,
      { method: 'DELETE' }
    );

    showCrudMessage(
      `Trip #${currentTripId} deleted successfully.`
    );

    currentTripId = null;

    await loadDashboard();
    await loadTrips();

  } catch (err) {
    showCrudMessage(err.message, true);
  }
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

refreshDashboardBtn
  .addEventListener('click', loadDashboard);

loadTripsBtn
  .addEventListener('click', loadTrips);

applyFiltersBtn
  .addEventListener('click', loadTrips);

clearFiltersBtn
  .addEventListener('click', async () => {
    clearFilters();
    await loadTrips();
  });

addCoordinateBtn
  ?.addEventListener(
    'click',
    () => addCoordinateRow()
  );

insertTripBtn
  ?.addEventListener(
    'click',
    insertTripFromForm
  );

updateTripBtn
  ?.addEventListener(
    'click',
    updateTripFromForm
  );

deleteTripBtn
  ?.addEventListener(
    'click',
    deleteSelectedTrip
  );

ensureMap();

Promise.all([
  loadDashboard(),
  loadTrips()
]).catch(err => {
  console.error(err);

  tripDetail.textContent =
    `Error loading dashboard: ${err.message}`;
});
