let map, routeLayer, markerLayer, circleLayer, currentTripId = null;
const formatNumber = (v, d = 2) => { const n = Number(v ?? 0); return Number.isFinite(n) ? n.toFixed(d) : '0.00'; };
const formatDate = v => !v ? '—' : new Date(v).toLocaleString();
const el = html => { const t = document.createElement('template'); t.innerHTML = html.trim(); return t.content.firstChild; };

function ensureMap() {
  if (map) return;
  map = L.map('map').setView([45.553, -94.154], 13);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution: '&copy; OpenStreetMap contributors' }).addTo(map);
  routeLayer = L.layerGroup().addTo(map);
  markerLayer = L.layerGroup().addTo(map);
  circleLayer = L.layerGroup().addTo(map);
}

async function fetchJSON(url, options = {}) {
  const res = await fetch(url, options);
  if (!res.ok) throw new Error(`Request failed: ${res.status}`);
  return res.json();
}

function renderSummary(summary) {
  const c = document.getElementById('summaryCards');
  c.innerHTML = '';
  [['Users', summary.users], ['Devices', summary.devices], ['Trips', summary.trips], ['Total Distance (km)', formatNumber(summary.total_distance_km)]].forEach(([label, value]) => {
    c.appendChild(el(`<div class="card"><div class="label">${label}</div><div class="value">${value}</div></div>`));
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
  renderSimpleList('topGeofences', data.top_geofences, item => el(`<div class="list-item"><strong>${item.geofence_name}</strong><br /><span class="muted">${item.crossing_count} crossing(s)</span></div>`));
  renderSimpleList('poiBreakdown', data.poi_breakdown, item => el(`<div class="list-item"><strong>${item.category}</strong><br /><span class="muted">${item.poi_count} POI(s)</span></div>`));
}

function buildTripsUrl() {
  const params = new URLSearchParams();
  [['user_id', filterUserId.value], ['device_id', filterDeviceId.value], ['tag', filterTag.value.trim()], ['min_distance', filterMinDistance.value], ['max_distance', filterMaxDistance.value]].forEach(([k, v]) => { if (v) params.set(k, v); });
  return '/api/trips' + (params.toString() ? `?${params.toString()}` : '');
}

async function loadTrips() {
  const trips = await fetchJSON(buildTripsUrl());
  const list = document.getElementById('tripList');
  list.innerHTML = '';
  if (!trips.length) { list.innerHTML = '<div class="empty-state">No trips matched those filters.</div>'; return; }
  trips.forEach(trip => {
    const item = el(`<div class="trip-item ${trip.trip_id === currentTripId ? 'active' : ''}" data-trip-id="${trip.trip_id}"><strong>Trip #${trip.trip_id}</strong><div class="meta">${trip.full_name}<br />${trip.device_name} (${trip.device_type})<br />${formatDate(trip.started_at)} → ${formatDate(trip.ended_at)}</div><div class="meta">Distance: ${formatNumber(trip.total_distance_km, 3)} km · Avg Speed: ${formatNumber(trip.avg_speed_kmh)} km/h · Stops: ${trip.stop_count}</div><div class="tags">Tags: ${trip.tags || 'none'}</div></div>`);
    item.addEventListener('click', () => selectTrip(trip.trip_id));
    list.appendChild(item);
  });
  if (!currentTripId && trips.length) await selectTrip(trips[0].trip_id);
}

function clearMapLayers() { routeLayer.clearLayers(); markerLayer.clearLayers(); circleLayer.clearLayers(); }

function renderTripDetail(detail) {
  const trip = detail.trip;
  detailChips.innerHTML = '';
  [`Trip #${trip.trip_id}`, `${trip.point_count} stored points`, `${detail.computed_stops.length} computed stops`, trip.tags ? `Tags: ${trip.tags}` : 'Tags: none'].forEach(text => detailChips.appendChild(el(`<span class="chip">${text}</span>`)));
  mapMeta.textContent = `${trip.full_name} · ${trip.device_name} · ${formatDate(trip.started_at)} to ${formatDate(trip.ended_at)}`;
  const stopItems = detail.stops.length ? `<ul>${detail.stops.map(s => `<li>${formatDate(s.started_at)} → ${formatDate(s.ended_at)} (${s.duration_seconds}s)</li>`).join('')}</ul>` : '<p class="muted">No stored stop events.</p>';
  const geofenceItems = detail.geofences.length ? `<ul>${detail.geofences.map(f => `<li>${f.geofence_name}: ${formatDate(f.entered_at)} → ${formatDate(f.exited_at)}</li>`).join('')}</ul>` : '<p class="muted">No geofence crossings recorded.</p>';
  tripDetail.className = 'trip-detail';
  tripDetail.innerHTML = `<div class="trip-detail-grid"><div class="detail-section"><h3>Stored Summary</h3><p>Total distance: <strong>${formatNumber(trip.total_distance_km, 3)} km</strong></p><p>Duration: <strong>${formatNumber(trip.duration_minutes)} min</strong></p><p>Average speed: <strong>${formatNumber(trip.avg_speed_kmh)} km/h</strong></p><p>Stops: <strong>${trip.stop_count}</strong></p></div><div class="detail-section"><h3>Computed Summary</h3><p>Total distance: <strong>${formatNumber(trip.computed_metrics.total_distance_km, 3)} km</strong></p><p>Duration: <strong>${formatNumber(trip.computed_metrics.duration_minutes)} min</strong></p><p>Average speed: <strong>${formatNumber(trip.computed_metrics.avg_speed_kmh)} km/h</strong></p><p>Points: <strong>${trip.computed_metrics.point_count}</strong></p></div><div class="detail-section"><h3>Route Health</h3><p>Status: <strong>${trip.status}</strong></p><p>Device: <strong>${trip.device_type}</strong></p><p>User: <strong>${trip.full_name}</strong></p></div></div><div class="detail-section"><h3>Stop Events</h3>${stopItems}</div><div class="detail-section"><h3>Geofence Crossings</h3>${geofenceItems}</div>`;
}

async function renderReferenceLayers() {
  const data = await fetchJSON('/api/reference');
  data.pois.forEach(poi => {
    const marker = L.circleMarker([poi.latitude, poi.longitude], { radius: 6 });
    marker.bindPopup(`<strong>${poi.poi_name}</strong><br />${poi.category}`);
    markerLayer.addLayer(marker);
  });
  data.geofences.forEach(fence => {
    const circle = L.circle([fence.center_lat, fence.center_lon], { radius: fence.radius_m, weight: 1.5, fillOpacity: .06 });
    circle.bindPopup(`<strong>${fence.geofence_name}</strong><br />Radius: ${fence.radius_m}m`);
    circleLayer.addLayer(circle);
  });
}

async function selectTrip(tripId) {
  currentTripId = tripId;
  [...document.querySelectorAll('.trip-item')].forEach(node => node.classList.toggle('active', Number(node.dataset.tripId) === tripId));
  const detail = await fetchJSON(`/api/trips/${tripId}`);
  renderTripDetail(detail);
  ensureMap();
  clearMapLayers();
  await renderReferenceLayers();
  const latlngs = detail.points.map(p => [p.latitude, p.longitude]);
  if (latlngs.length) {
    const polyline = L.polyline(latlngs, { weight: 4 }).addTo(routeLayer);
    map.fitBounds(polyline.getBounds(), { padding: [30, 30] });
    const first = detail.points[0], last = detail.points[detail.points.length - 1];
    L.marker([first.latitude, first.longitude]).bindPopup('Trip start').addTo(routeLayer);
    L.marker([last.latitude, last.longitude]).bindPopup('Trip end').addTo(routeLayer);
  }
  detail.stops.forEach(stop => L.circleMarker([stop.latitude, stop.longitude], { radius: 8 }).bindPopup(`<strong>Stop event</strong><br />${formatDate(stop.started_at)}<br />${stop.duration_seconds}s`).addTo(routeLayer));
}

function clearFilters() { ['filterUserId', 'filterDeviceId', 'filterTag', 'filterMinDistance', 'filterMaxDistance'].forEach(id => document.getElementById(id).value = ''); }

refreshDashboardBtn.addEventListener('click', loadDashboard);
loadTripsBtn.addEventListener('click', loadTrips);
applyFiltersBtn.addEventListener('click', loadTrips);
clearFiltersBtn.addEventListener('click', async () => { clearFilters(); await loadTrips(); });

ensureMap();
Promise.all([loadDashboard(), loadTrips()]).catch(err => {
  console.error(err);
  tripDetail.textContent = `Error loading dashboard: ${err.message}`;
});
