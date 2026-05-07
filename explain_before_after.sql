-- Indexing & Query Optimization demo for PostgreSQL
-- Requirement: show EXPLAIN PLAN output before and after adding an index.

-- 1) BEFORE INDEX
DROP INDEX IF EXISTS idx_demo_gps_points_trip_recorded;
DROP INDEX IF EXISTS idx_gps_points_trip_recorded;
ANALYZE gps_points;

EXPLAIN (ANALYZE, BUFFERS)
SELECT point_id, latitude, longitude, recorded_at
FROM gps_points
WHERE trip_id = 1
ORDER BY recorded_at;

-- 2) ADD INDEX
CREATE INDEX idx_demo_gps_points_trip_recorded
ON gps_points(trip_id, recorded_at);
ANALYZE gps_points;

-- 3) AFTER INDEX
EXPLAIN (ANALYZE, BUFFERS)
SELECT point_id, latitude, longitude, recorded_at
FROM gps_points
WHERE trip_id = 1
ORDER BY recorded_at;


