CREATE EXTENSION IF NOT EXISTS postgis;

DROP TABLE IF EXISTS geofence_crossings CASCADE;
DROP TABLE IF EXISTS stop_events CASCADE;
DROP TABLE IF EXISTS gps_points CASCADE;
DROP TABLE IF EXISTS trip_tag_map CASCADE;
DROP TABLE IF EXISTS trip_summaries CASCADE;
DROP TABLE IF EXISTS trips CASCADE;
DROP TABLE IF EXISTS trip_tags CASCADE;
DROP TABLE IF EXISTS pois CASCADE;
DROP TABLE IF EXISTS geofences CASCADE;
DROP TABLE IF EXISTS devices CASCADE;
DROP TABLE IF EXISTS users_account CASCADE;

CREATE TABLE users_account (
    user_id SERIAL PRIMARY KEY,
    full_name VARCHAR(120) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE devices (
    device_id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users_account(user_id) ON DELETE CASCADE,
    device_name VARCHAR(120) NOT NULL,
    device_type VARCHAR(50) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE trips (
    trip_id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users_account(user_id) ON DELETE CASCADE,
    device_id INTEGER NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ,
    status VARCHAR(20) NOT NULL DEFAULT 'in_progress' CHECK (status IN ('in_progress', 'completed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE gps_points (
    point_id BIGSERIAL PRIMARY KEY,
    trip_id INTEGER NOT NULL REFERENCES trips(trip_id) ON DELETE CASCADE,
    latitude NUMERIC(9,6) NOT NULL CHECK (latitude BETWEEN -90 AND 90),
    longitude NUMERIC(9,6) NOT NULL CHECK (longitude BETWEEN -180 AND 180),
    recorded_at TIMESTAMPTZ NOT NULL,
    accuracy_m NUMERIC(8,2),
    speed_kmh NUMERIC(8,2),
    location geography(Point, 4326) GENERATED ALWAYS AS
        (ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography) STORED,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE stop_events (
    stop_id SERIAL PRIMARY KEY,
    trip_id INTEGER NOT NULL REFERENCES trips(trip_id) ON DELETE CASCADE,
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ NOT NULL,
    latitude NUMERIC(9,6) NOT NULL,
    longitude NUMERIC(9,6) NOT NULL,
    duration_seconds INTEGER NOT NULL CHECK (duration_seconds >= 0),
    nearest_poi_id INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE geofences (
    geofence_id SERIAL PRIMARY KEY,
    geofence_name VARCHAR(120) NOT NULL UNIQUE,
    center_lat NUMERIC(9,6) NOT NULL,
    center_lon NUMERIC(9,6) NOT NULL,
    radius_m NUMERIC(10,2) NOT NULL CHECK (radius_m > 0),
    location geography(Point, 4326) GENERATED ALWAYS AS
        (ST_SetSRID(ST_MakePoint(center_lon, center_lat), 4326)::geography) STORED,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE geofence_crossings (
    crossing_id SERIAL PRIMARY KEY,
    trip_id INTEGER NOT NULL REFERENCES trips(trip_id) ON DELETE CASCADE,
    geofence_id INTEGER NOT NULL REFERENCES geofences(geofence_id) ON DELETE CASCADE,
    entered_at TIMESTAMPTZ NOT NULL,
    exited_at TIMESTAMPTZ,
    UNIQUE (trip_id, geofence_id, entered_at)
);

CREATE TABLE pois (
    poi_id SERIAL PRIMARY KEY,
    poi_name VARCHAR(120) NOT NULL,
    category VARCHAR(80) NOT NULL,
    latitude NUMERIC(9,6) NOT NULL,
    longitude NUMERIC(9,6) NOT NULL,
    location geography(Point, 4326) GENERATED ALWAYS AS
        (ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography) STORED
);

ALTER TABLE stop_events
    ADD CONSTRAINT fk_stop_nearest_poi
    FOREIGN KEY (nearest_poi_id) REFERENCES pois(poi_id) ON DELETE SET NULL;

CREATE TABLE trip_tags (
    tag_id SERIAL PRIMARY KEY,
    tag_name VARCHAR(60) NOT NULL UNIQUE
);

CREATE TABLE trip_tag_map (
    trip_id INTEGER NOT NULL REFERENCES trips(trip_id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES trip_tags(tag_id) ON DELETE CASCADE,
    PRIMARY KEY (trip_id, tag_id)
);

CREATE TABLE trip_summaries (
    trip_id INTEGER PRIMARY KEY REFERENCES trips(trip_id) ON DELETE CASCADE,
    point_count INTEGER NOT NULL DEFAULT 0,
    total_distance_km NUMERIC(14,6) NOT NULL DEFAULT 0,
    duration_minutes NUMERIC(10,2) NOT NULL DEFAULT 0,
    avg_speed_kmh NUMERIC(10,2) NOT NULL DEFAULT 0,
    stop_count INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_trips_user_started ON trips(user_id, started_at DESC);
CREATE INDEX idx_trips_device_started ON trips(device_id, started_at DESC);
CREATE INDEX idx_gps_points_trip_recorded ON gps_points(trip_id, recorded_at);
CREATE INDEX idx_gps_points_location_gist ON gps_points USING GIST (location);
CREATE INDEX idx_pois_location_gist ON pois USING GIST (location);
CREATE INDEX idx_geofences_location_gist ON geofences USING GIST (location);
CREATE INDEX idx_stop_events_trip_started ON stop_events(trip_id, started_at);
CREATE INDEX idx_geofence_crossings_trip ON geofence_crossings(trip_id, entered_at);

-- Additional indexes for RoutePulse query optimization to support dashboard filtering, tag searches, summary joins,stop-to-POI lookup, and geofence lookup.

CREATE INDEX idx_devices_user_id ON devices(user_id);
CREATE INDEX idx_trips_status ON trips(status);
CREATE INDEX idx_trip_tag_map_tag_id ON trip_tag_map(tag_id);
CREATE INDEX idx_trip_tags_tag_name ON trip_tags(tag_name);
CREATE INDEX idx_stop_events_nearest_poi_id ON stop_events(nearest_poi_id);
CREATE INDEX idx_geofence_crossings_geofence_id ON geofence_crossings(geofence_id);
CREATE INDEX idx_pois_category ON pois(category);

-- Extra indexes added for the UI filter and optimization demo.
-- LOWER(tag_name) matches the Flask filter LOWER(raw_tag.tag_name) = LOWER(%s).
CREATE INDEX idx_trip_tags_lower_tag_name ON trip_tags (LOWER(tag_name));

-- Helps min/max distance filtering through v_trip_overview / trip_summaries.
CREATE INDEX idx_trip_summaries_total_distance ON trip_summaries(total_distance_km);

-- Helps common dashboard sorting when no user/device filter is selected.
CREATE INDEX idx_trips_started_at_desc ON trips(started_at DESC);
