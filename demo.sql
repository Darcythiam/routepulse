BEGIN;

INSERT INTO trips (user_id, device_id, started_at, status)
VALUES (1, 1, NOW(), 'in_progress');

SAVEPOINT trip_save;

INSERT INTO gps_points (
    trip_id,
    latitude,
    longitude,
    recorded_at
)
VALUES (
    999,
    120,
    -300,
    NOW()
);

ROLLBACK TO SAVEPOINT trip_save;

COMMIT;