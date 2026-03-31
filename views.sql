CREATE OR REPLACE VIEW v_trip_overview AS
SELECT
    t.trip_id,
    t.user_id,
    t.device_id,
    u.full_name,
    d.device_name,
    d.device_type,
    t.started_at,
    t.ended_at,
    t.status,
    COALESCE(ts.total_distance_km, 0) AS total_distance_km,
    COALESCE(ts.duration_minutes, 0) AS duration_minutes,
    COALESCE(ts.avg_speed_kmh, 0) AS avg_speed_kmh,
    COALESCE(ts.stop_count, 0) AS stop_count,
    COALESCE(ts.point_count, 0) AS point_count
FROM trips t
JOIN users_account u ON u.user_id = t.user_id
JOIN devices d ON d.device_id = t.device_id
LEFT JOIN trip_summaries ts ON ts.trip_id = t.trip_id;

CREATE OR REPLACE VIEW v_top_geofences AS
SELECT g.geofence_name, COUNT(*) AS crossing_count
FROM geofence_crossings gc
JOIN geofences g ON g.geofence_id = gc.geofence_id
GROUP BY g.geofence_name
ORDER BY crossing_count DESC, g.geofence_name;

CREATE OR REPLACE VIEW v_trip_tags AS
SELECT t.trip_id, STRING_AGG(tt.tag_name, ', ' ORDER BY tt.tag_name) AS tags
FROM trips t
LEFT JOIN trip_tag_map tm ON tm.trip_id = t.trip_id
LEFT JOIN trip_tags tt ON tt.tag_id = tm.tag_id
GROUP BY t.trip_id;
