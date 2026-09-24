-- Use on an existing RoutePulse database. schema.sql is for fresh databases only.
BEGIN;
CREATE EXTENSION IF NOT EXISTS postgis;
ALTER TABLE gps_points ADD COLUMN IF NOT EXISTS location geography(Point, 4326)
    GENERATED ALWAYS AS (ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography) STORED;
ALTER TABLE pois ADD COLUMN IF NOT EXISTS location geography(Point, 4326)
    GENERATED ALWAYS AS (ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography) STORED;
ALTER TABLE geofences ADD COLUMN IF NOT EXISTS location geography(Point, 4326)
    GENERATED ALWAYS AS (ST_SetSRID(ST_MakePoint(center_lon, center_lat), 4326)::geography) STORED;
CREATE INDEX IF NOT EXISTS idx_gps_points_location_gist ON gps_points USING GIST (location);
CREATE INDEX IF NOT EXISTS idx_pois_location_gist ON pois USING GIST (location);
CREATE INDEX IF NOT EXISTS idx_geofences_location_gist ON geofences USING GIST (location);
ALTER TABLE trip_summaries ALTER COLUMN total_distance_km TYPE NUMERIC(14,6);
COMMIT;
