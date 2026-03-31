CREATE OR REPLACE FUNCTION ensure_trip_summary_row()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO trip_summaries (trip_id)
    VALUES (NEW.trip_id)
    ON CONFLICT (trip_id) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_trip_summary_seed ON trips;
CREATE TRIGGER trg_trip_summary_seed
AFTER INSERT ON trips
FOR EACH ROW
EXECUTE FUNCTION ensure_trip_summary_row();

CREATE OR REPLACE VIEW trip_points_ordered AS
SELECT
    gp.*,
    ROW_NUMBER() OVER (PARTITION BY trip_id ORDER BY recorded_at) AS seq,
    LAG(latitude) OVER (PARTITION BY trip_id ORDER BY recorded_at) AS prev_latitude,
    LAG(longitude) OVER (PARTITION BY trip_id ORDER BY recorded_at) AS prev_longitude,
    LAG(recorded_at) OVER (PARTITION BY trip_id ORDER BY recorded_at) AS prev_recorded_at
FROM gps_points gp;
