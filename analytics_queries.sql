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
