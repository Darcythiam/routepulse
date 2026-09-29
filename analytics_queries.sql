SELECT * FROM v_trip_overview ORDER BY total_distance_km DESC LIMIT 10;
SELECT * FROM v_top_geofences;
SELECT
    CASE
        WHEN EXTRACT(HOUR FROM started_at) BETWEEN 5 AND 10 THEN 'Morning'
        WHEN EXTRACT(HOUR FROM started_at) BETWEEN 11 AND 16 THEN 'Midday'
        WHEN EXTRACT(HOUR FROM started_at) BETWEEN 17 AND 21 THEN 'Evening'
        ELSE 'Night'
    END AS time_bucket,
    ROUND(AVG(total_distance_km), 2) AS avg_distance_km,
    ROUND(AVG(avg_speed_kmh), 2) AS avg_speed_kmh,
    COUNT(*) AS trip_count
FROM v_trip_overview
GROUP BY time_bucket
ORDER BY trip_count DESC;

-- ============================================================
-- RoutePulse Query Optimization / Benchmark Queries
-- These EXPLAIN ANALYZE queries are used to verify that indexes
-- support common dashboard and trip-detail operations.
-- ============================================================

-- 1. Dashboard trip filter by user
-- Supported by idx_trips_user_started
EXPLAIN ANALYZE
SELECT
    trip_id,
    user_id,
    device_id,
    started_at,
    ended_at,
    status
FROM trips
WHERE user_id = 1
ORDER BY started_at DESC;

-- 2. Dashboard trip filter by device
-- Supported by idx_trips_device_started
EXPLAIN ANALYZE
SELECT
    trip_id,
    user_id,
    device_id,
    started_at,
    ended_at,
    status
FROM trips
WHERE device_id = 2
ORDER BY started_at DESC;

-- 3. Trip detail route loading
-- Supported by idx_gps_points_trip_recorded
EXPLAIN ANALYZE
SELECT
    point_id,
    trip_id,
    latitude,
    longitude,
    recorded_at,
    accuracy_m,
    speed_kmh
FROM gps_points
WHERE trip_id = 8
ORDER BY recorded_at;

-- 4. Stop events for selected trip
-- Supported by idx_stop_events_trip_started
EXPLAIN ANALYZE
SELECT
    stop_id,
    trip_id,
    started_at,
    ended_at,
    latitude,
    longitude,
    duration_seconds,
    nearest_poi_id
FROM stop_events
WHERE trip_id = 10
ORDER BY started_at;

-- 5. Geofence crossings for selected trip
-- Supported by idx_geofence_crossings_trip
EXPLAIN ANALYZE
SELECT
    crossing_id,
    trip_id,
    geofence_id,
    entered_at,
    exited_at
FROM geofence_crossings
WHERE trip_id = 8
ORDER BY entered_at;

-- 6. Tag-based trip lookup
-- Supported by idx_trip_tags_tag_name and idx_trip_tag_map_tag_id
EXPLAIN ANALYZE
SELECT
    t.trip_id,
    t.user_id,
    t.device_id,
    t.started_at,
    t.ended_at,
    tt.tag_name
FROM trips t
JOIN trip_tag_map ttm ON t.trip_id = ttm.trip_id
JOIN trip_tags tt ON ttm.tag_id = tt.tag_id
WHERE tt.tag_name = 'commute'
ORDER BY t.started_at DESC;

-- 7. Dashboard aggregate summary
-- Uses trip_summaries and base tables for project-level metrics
EXPLAIN ANALYZE
SELECT
    COUNT(DISTINCT u.user_id) AS users,
    COUNT(DISTINCT d.device_id) AS devices,
    COUNT(DISTINCT t.trip_id) AS trips,
    ROUND(COALESCE(SUM(ts.total_distance_km), 0), 2) AS total_distance_km
FROM users_account u
LEFT JOIN devices d ON d.user_id = u.user_id
LEFT JOIN trips t ON t.user_id = u.user_id
LEFT JOIN trip_summaries ts ON ts.trip_id = t.trip_id;

-- 8. POI category breakdown
-- Supported by idx_pois_category
EXPLAIN ANALYZE
SELECT
    category,
    COUNT(*) AS poi_count
FROM pois
GROUP BY category
ORDER BY category;