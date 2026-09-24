import math
import os
import time
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras
import redis
from dotenv import load_dotenv
from flask import Flask, Response, g, jsonify, render_template, request
from flask_sock import Sock
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from simple_websocket import ConnectionClosed

load_dotenv()
app = Flask(__name__)
sock = Sock(app)
cache = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True,
                       socket_connect_timeout=1, socket_timeout=1)
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "60"))
CACHE_ENABLED = os.getenv("CACHE_ENABLED", "1") == "1"
HTTP_REQUESTS = Counter("routepulse_http_requests_total", "HTTP responses", ["method", "route", "status"])
HTTP_DURATION = Histogram("routepulse_http_request_duration_seconds", "HTTP request duration", ["method", "route"])
CACHE_ACCESSES = Counter("routepulse_cache_access_total", "Trip cache access", ["result"])
POSITION_EVENTS = Counter("routepulse_position_events_total", "Published GPS positions")


@app.before_request
def start_timer():
    g.request_started_at = time.monotonic()


@app.after_request
def record_request(response):
    if request.path != "/metrics":
        route = request.url_rule.rule if request.url_rule else "unmatched"
        HTTP_REQUESTS.labels(request.method, route, str(response.status_code)).inc()
        HTTP_DURATION.labels(request.method, route).observe(time.monotonic() - g.request_started_at)
    return response


@app.route("/metrics")
def metrics():
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)


@app.route("/api/health/live")
def live():
    return jsonify({"status": "ok"})


@app.route("/api/health/ready")
def ready():
    try:
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        finally:
            conn.close()
        cache.ping()
    except (psycopg2.Error, redis.RedisError):
        return jsonify({"status": "unavailable"}), 503
    return jsonify({"status": "ok"})


def cache_key(trip_id):
    return f"routepulse:trip:{trip_id}"


def invalidate_trip(trip_id):
    try:
        cache.delete(cache_key(trip_id))
    except redis.RedisError:
        CACHE_ACCESSES.labels("error").inc()


def cached_trip_detail(trip_id):
    if not CACHE_ENABLED:
        return fetch_trip_detail(trip_id)
    try:
        cached = cache.get(cache_key(trip_id))
        if cached is not None:
            CACHE_ACCESSES.labels("hit").inc()
            return app.json.loads(cached)
        CACHE_ACCESSES.labels("miss").inc()
    except redis.RedisError:
        CACHE_ACCESSES.labels("error").inc()
    detail = fetch_trip_detail(trip_id)
    if detail is not None:
        try:
            cache.setex(cache_key(trip_id), CACHE_TTL_SECONDS, app.json.dumps(detail))
        except redis.RedisError:
            CACHE_ACCESSES.labels("error").inc()
    return detail


def publish_position(trip_id, position):
    try:
        cache.publish(f"routepulse:trip:{trip_id}:positions", app.json.dumps(position))
        POSITION_EVENTS.inc()
    except redis.RedisError:
        CACHE_ACCESSES.labels("error").inc()


@sock.route("/ws/trips/<int:trip_id>")
def stream_positions(ws, trip_id):
    """Subscribe before requesting the trip snapshot to avoid missing new points."""
    pubsub = cache.pubsub()
    try:
        pubsub.subscribe(f"routepulse:trip:{trip_id}:positions")
        ws.send(app.json.dumps({"type": "subscribed", "trip_id": trip_id}))
        last_heartbeat = time.monotonic()
        while ws.connected:
            message = pubsub.get_message(ignore_subscribe_messages=True, timeout=1)
            if message:
                ws.send(message["data"])
            if time.monotonic() - last_heartbeat > 15:
                ws.send(app.json.dumps({"type": "heartbeat"}))
                last_heartbeat = time.monotonic()
    except (redis.RedisError, ConnectionClosed, OSError):
        pass
    finally:
        try:
            pubsub.close()
        except redis.RedisError:
            pass


def get_db_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "routepulse"),
        user=os.getenv("DB_USER", "routeuser"),
        password=os.getenv("DB_PASS", "local-only-password"),
        cursor_factory=psycopg2.extras.RealDictCursor,
    )


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1 = math.radians(float(lat1))
    p2 = math.radians(float(lat2))
    dphi = math.radians(float(lat2) - float(lat1))
    dlambda = math.radians(float(lon2) - float(lon1))
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def iso(value):
    return None if value is None else value.astimezone(timezone.utc).isoformat()


def compute_trip_metrics(points):
    if len(points) < 2:
        return {"point_count": len(points), "total_distance_km": 0.0, "duration_minutes": 0.0, "avg_speed_kmh": 0.0}
    total_distance = 0.0
    for prev, curr in zip(points, points[1:]):
        total_distance += haversine_km(prev["latitude"], prev["longitude"], curr["latitude"], curr["longitude"])
    duration_seconds = (points[-1]["recorded_at"] - points[0]["recorded_at"]).total_seconds()
    duration_minutes = max(duration_seconds / 60.0, 0.0)
    avg_speed_kmh = total_distance / (duration_seconds / 3600.0) if duration_seconds > 0 else 0.0
    return {
        "point_count": len(points),
        "total_distance_km": round(total_distance, 3),
        "duration_minutes": round(duration_minutes, 2),
        "avg_speed_kmh": round(avg_speed_kmh, 2),
    }


def detect_stop_events(points, distance_threshold_m=35, min_stop_seconds=180):
    if len(points) < 2:
        return []
    stops = []
    cluster = [points[0]]
    for point in points[1:]:
        last = cluster[-1]
        distance_m = haversine_km(last["latitude"], last["longitude"], point["latitude"], point["longitude"]) * 1000
        if distance_m <= distance_threshold_m:
            cluster.append(point)
        else:
            duration = (cluster[-1]["recorded_at"] - cluster[0]["recorded_at"]).total_seconds()
            if duration >= min_stop_seconds:
                avg_lat = sum(float(p["latitude"]) for p in cluster) / len(cluster)
                avg_lon = sum(float(p["longitude"]) for p in cluster) / len(cluster)
                stops.append({
                    "started_at": cluster[0]["recorded_at"],
                    "ended_at": cluster[-1]["recorded_at"],
                    "latitude": round(avg_lat, 6),
                    "longitude": round(avg_lon, 6),
                    "duration_seconds": int(duration),
                })
            cluster = [point]
    duration = (cluster[-1]["recorded_at"] - cluster[0]["recorded_at"]).total_seconds()
    if duration >= min_stop_seconds:
        avg_lat = sum(float(p["latitude"]) for p in cluster) / len(cluster)
        avg_lon = sum(float(p["longitude"]) for p in cluster) / len(cluster)
        stops.append({
            "started_at": cluster[0]["recorded_at"],
            "ended_at": cluster[-1]["recorded_at"],
            "latitude": round(avg_lat, 6),
            "longitude": round(avg_lon, 6),
            "duration_seconds": int(duration),
        })
    return stops


def fetch_trip_detail(trip_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT o.*, COALESCE(tt.tags, '') AS tags
                FROM v_trip_overview o
                LEFT JOIN v_trip_tags tt ON tt.trip_id = o.trip_id
                WHERE o.trip_id = %s
                """,
                (trip_id,),
            )
            trip = cur.fetchone()
            if not trip:
                return None

            cur.execute(
                "SELECT point_id, latitude, longitude, recorded_at, accuracy_m, speed_kmh FROM gps_points WHERE trip_id = %s ORDER BY recorded_at",
                (trip_id,),
            )
            points = cur.fetchall()

            cur.execute(
                "SELECT stop_id, started_at, ended_at, latitude, longitude, duration_seconds, nearest_poi_id FROM stop_events WHERE trip_id = %s ORDER BY started_at",
                (trip_id,),
            )
            stops = [dict(s) for s in cur.fetchall()]

            cur.execute(
                """
                SELECT gc.crossing_id, gc.entered_at, gc.exited_at, g.geofence_name, g.center_lat, g.center_lon, g.radius_m
                FROM geofence_crossings gc
                JOIN geofences g ON g.geofence_id = gc.geofence_id
                WHERE gc.trip_id = %s
                ORDER BY gc.entered_at
                """,
                (trip_id,),
            )
            geofences = cur.fetchall()

        trip_dict = dict(trip)
        return {
            "trip": {
                **trip_dict,
                "started_at": iso(trip_dict["started_at"]),
                "ended_at": iso(trip_dict["ended_at"]),
                "computed_metrics": compute_trip_metrics(points),
            },
            "points": [{**dict(p), "recorded_at": iso(dict(p)["recorded_at"])} for p in points],
            "stops": [{**dict(s), "started_at": iso(dict(s)["started_at"]), "ended_at": iso(dict(s)["ended_at"])} for s in stops],
            "computed_stops": [{**dict(s), "started_at": iso(dict(s)["started_at"]), "ended_at": iso(dict(s)["ended_at"])} for s in detect_stop_events(points)],
            "geofences": [{**dict(g), "entered_at": iso(dict(g)["entered_at"]), "exited_at": iso(dict(g)["exited_at"])} for g in geofences],
        }
    finally:
        conn.close()


def nearest_poi_id(cur, lat, lon, max_distance_m=120):
    cur.execute("""
        SELECT poi_id FROM pois
        WHERE ST_DWithin(location, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, %s)
        ORDER BY ST_Distance(location, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography)
        LIMIT 1
    """, (lon, lat, max_distance_m, lon, lat))
    row = cur.fetchone()
    return row["poi_id"] if row else None


def refresh_trip_summary(cur, trip_id):
    cur.execute("SELECT point_id, latitude, longitude, recorded_at FROM gps_points WHERE trip_id = %s ORDER BY recorded_at", (trip_id,))
    points = cur.fetchall()
    metrics = compute_trip_metrics(points)
    computed_stops = detect_stop_events(points)

    cur.execute("DELETE FROM stop_events WHERE trip_id = %s", (trip_id,))
    for stop in computed_stops:
        poi_id = nearest_poi_id(cur, stop["latitude"], stop["longitude"])
        cur.execute(
            "INSERT INTO stop_events (trip_id, started_at, ended_at, latitude, longitude, duration_seconds, nearest_poi_id) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (trip_id, stop["started_at"], stop["ended_at"], stop["latitude"], stop["longitude"], stop["duration_seconds"], poi_id),
        )

    cur.execute("DELETE FROM geofence_crossings WHERE trip_id = %s", (trip_id,))
    cur.execute("SELECT geofence_id, center_lat, center_lon, radius_m FROM geofences")
    geofences = cur.fetchall()
    active = {}
    for point in points:
        for fence in geofences:
            distance_m = haversine_km(point["latitude"], point["longitude"], fence["center_lat"], fence["center_lon"]) * 1000
            inside = distance_m <= float(fence["radius_m"])
            key = fence["geofence_id"]
            if inside and key not in active:
                active[key] = point["recorded_at"]
            elif not inside and key in active:
                cur.execute(
                    "INSERT INTO geofence_crossings (trip_id, geofence_id, entered_at, exited_at) VALUES (%s, %s, %s, %s)",
                    (trip_id, key, active[key], point["recorded_at"]),
                )
                active.pop(key, None)
    for fence_id, entered_at in active.items():
        cur.execute(
            "INSERT INTO geofence_crossings (trip_id, geofence_id, entered_at, exited_at) VALUES (%s, %s, %s, %s)",
            (trip_id, fence_id, entered_at, points[-1]["recorded_at"] if points else None),
        )

    cur.execute(
        """
        INSERT INTO trip_summaries (trip_id, point_count, total_distance_km, duration_minutes, avg_speed_kmh, stop_count, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (trip_id) DO UPDATE SET
            point_count = EXCLUDED.point_count,
            total_distance_km = EXCLUDED.total_distance_km,
            duration_minutes = EXCLUDED.duration_minutes,
            avg_speed_kmh = EXCLUDED.avg_speed_kmh,
            stop_count = EXCLUDED.stop_count,
            updated_at = NOW()
        """,
        (trip_id, metrics["point_count"], metrics["total_distance_km"], metrics["duration_minutes"], metrics["avg_speed_kmh"], len(computed_stops)),
    )


def update_summary_for_point(cur, trip_id, point_id, recorded_at):
    """Update cheap counters on ingestion; derive stops/geofences when the trip ends."""
    cur.execute("""
        SELECT COALESCE(ST_Distance(gp.location, prev.location) / 1000.0, 0) AS km
        FROM gps_points gp
        LEFT JOIN LATERAL (
            SELECT location FROM gps_points
            WHERE trip_id = %s AND recorded_at < gp.recorded_at
            ORDER BY recorded_at DESC LIMIT 1
        ) prev ON true
        WHERE gp.point_id = %s
    """, (trip_id, point_id))
    distance_km = float(cur.fetchone()["km"])
    cur.execute("SELECT recorded_at FROM gps_points WHERE trip_id = %s ORDER BY recorded_at LIMIT 1", (trip_id,))
    first_at = cur.fetchone()["recorded_at"]
    duration_minutes = max((recorded_at - first_at).total_seconds() / 60.0, 0.0)
    cur.execute("""
        UPDATE trip_summaries SET
            point_count = point_count + 1,
            total_distance_km = total_distance_km + %s,
            duration_minutes = %s,
            avg_speed_kmh = CASE WHEN %s > 0 THEN (total_distance_km + %s) / (%s / 60.0) ELSE 0 END,
            updated_at = NOW()
        WHERE trip_id = %s
    """, (distance_km, duration_minutes, duration_minutes, distance_km, duration_minutes, trip_id))


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/api/dashboard")
def dashboard():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            def _fetch_value(row, key='count', default=0, cast=int):
                if not row:
                    return default
                # support both mapping-like rows and sequence rows
                if hasattr(row, 'get'):
                    return cast(row.get(key, default))
                try:
                    return cast(row[0])
                except Exception:
                    return default

            cur.execute("SELECT COUNT(*) AS count FROM users_account")
            row = cur.fetchone()
            users = _fetch_value(row, 'count', 0, int)

            cur.execute("SELECT COUNT(*) AS count FROM devices")
            row = cur.fetchone()
            devices = _fetch_value(row, 'count', 0, int)

            cur.execute("SELECT COUNT(*) AS count FROM trips")
            row = cur.fetchone()
            trips = _fetch_value(row, 'count', 0, int)

            cur.execute("SELECT COALESCE(SUM(total_distance_km), 0) AS total_distance_km FROM trip_summaries")
            row = cur.fetchone()
            total_distance = _fetch_value(row, 'total_distance_km', 0.0, float)
            cur.execute("SELECT geofence_name, crossing_count FROM v_top_geofences LIMIT 5")
            top_geofences = cur.fetchall()
            cur.execute("SELECT category, COUNT(*) AS poi_count FROM pois GROUP BY category ORDER BY poi_count DESC, category")
            poi_breakdown = cur.fetchall()
        return jsonify({
            "summary": {"users": users, "devices": devices, "trips": trips, "total_distance_km": round(total_distance, 2)},
            "top_geofences": top_geofences,
            "poi_breakdown": poi_breakdown,
        })
    finally:
        conn.close()


@app.route("/api/trips")
def list_trips():
    user_id = request.args.get("user_id")
    device_id = request.args.get("device_id")
    tag = request.args.get("tag")
    min_distance = request.args.get("min_distance")
    max_distance = request.args.get("max_distance")

    query = "SELECT o.*, COALESCE(tt.tags, '') AS tags FROM v_trip_overview o LEFT JOIN v_trip_tags tt ON tt.trip_id = o.trip_id"
    params = []
    filters = []
    if tag:
        query += " LEFT JOIN trip_tag_map ttm ON ttm.trip_id = o.trip_id LEFT JOIN trip_tags raw_tag ON raw_tag.tag_id = ttm.tag_id"
    if user_id:
        filters.append("o.user_id = %s")
        params.append(user_id)
    if device_id:
        filters.append("o.device_id = %s")
        params.append(device_id)
    if tag:
        filters.append("LOWER(raw_tag.tag_name) = LOWER(%s)")
        params.append(tag)
    if min_distance:
        filters.append("o.total_distance_km >= %s")
        params.append(min_distance)
    if max_distance:
        filters.append("o.total_distance_km <= %s")
        params.append(max_distance)
    if filters:
        query += " WHERE " + " AND ".join(filters)
    query += " ORDER BY o.started_at DESC"

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
        return jsonify([{**dict(row), "started_at": iso(dict(row)["started_at"]), "ended_at": iso(dict(row)["ended_at"])} for row in rows])
    finally:
        conn.close()


@app.route("/api/trips/<int:trip_id>")
def trip_detail(trip_id):
    detail = cached_trip_detail(trip_id)
    if not detail:
        return jsonify({"error": "Trip not found"}), 404
    return jsonify(detail)


@app.route("/api/reference")
def reference_data():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT geofence_id, geofence_name, center_lat, center_lon, radius_m FROM geofences ORDER BY geofence_name")
            geofences = cur.fetchall()
            cur.execute("SELECT poi_id, poi_name, category, latitude, longitude FROM pois ORDER BY poi_name")
            pois = cur.fetchall()
        return jsonify({"geofences": geofences, "pois": pois})
    finally:
        conn.close()


@app.route("/api/nearby/points")
def nearby_points():
    try:
        lat = float(request.args["lat"])
        lon = float(request.args["lon"])
        radius_m = float(request.args.get("radius_m", "500"))
        limit = int(request.args.get("limit", "100"))
        if not (-90 <= lat <= 90 and -180 <= lon <= 180 and 0 < radius_m <= 10000 and 1 <= limit <= 500):
            raise ValueError("out of range")
    except (KeyError, ValueError):
        return jsonify({"error": "Specify valid lat, lon, radius_m (0-10000), and limit (1-500)."}), 400
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT point_id, trip_id, latitude, longitude, recorded_at,
                    ST_Distance(location, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography) AS distance_m
                FROM gps_points
                WHERE ST_DWithin(location, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, %s)
                ORDER BY distance_m, point_id LIMIT %s
            """, (lon, lat, lon, lat, radius_m, limit))
            rows = cur.fetchall()
        return jsonify([{**dict(row), "recorded_at": iso(row["recorded_at"])} for row in rows])
    finally:
        conn.close()


@app.route("/api/trips/start", methods=["POST"])
def start_trip():
    payload = request.get_json(force=True)
    required = ["user_id", "device_id", "started_at"]
    missing = [field for field in required if field not in payload]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

    conn = get_db_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO trips (user_id, device_id, started_at, status) VALUES (%s, %s, %s, 'in_progress') RETURNING trip_id",
                    (payload["user_id"], payload["device_id"], payload["started_at"]),
                )
                trip_id = cur.fetchone()["trip_id"]
        return jsonify({"trip_id": trip_id, "status": "in_progress"}), 201
    finally:
        conn.close()


@app.route("/api/trips/<int:trip_id>/points", methods=["POST"])
def add_trip_point(trip_id):
    payload = request.get_json(silent=True) or {}
    required = ["latitude", "longitude", "recorded_at"]
    missing = [field for field in required if field not in payload]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400
    lat, lon, error = validate_lat_lon(payload["latitude"], payload["longitude"])
    if error:
        return jsonify({"error": error}), 400
    try:
        recorded_at = datetime.fromisoformat(payload["recorded_at"].replace("Z", "+00:00"))
        if recorded_at.tzinfo is None:
            raise ValueError("timezone required")
    except (AttributeError, ValueError):
        return jsonify({"error": "recorded_at must be an ISO 8601 timestamp with a timezone."}), 400

    conn = get_db_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT status, started_at FROM trips WHERE trip_id = %s FOR UPDATE", (trip_id,))
                trip = cur.fetchone()
                if not trip:
                    return jsonify({"error": "Trip not found"}), 404
                if trip["status"] != "in_progress":
                    return jsonify({"error": "Trip is already completed"}), 409
                cur.execute("SELECT MAX(recorded_at) AS latest FROM gps_points WHERE trip_id = %s", (trip_id,))
                latest = cur.fetchone()["latest"]
                if recorded_at < trip["started_at"] or (latest and recorded_at <= latest):
                    return jsonify({"error": "recorded_at must be after the prior point and not before trip start."}), 400
                cur.execute(
                    "INSERT INTO gps_points (trip_id, latitude, longitude, recorded_at, accuracy_m, speed_kmh) VALUES (%s, %s, %s, %s, %s, %s) RETURNING point_id",
                    (trip_id, lat, lon, recorded_at, payload.get("accuracy_m"), payload.get("speed_kmh")),
                )
                point_id = cur.fetchone()["point_id"]
                update_summary_for_point(cur, trip_id, point_id, recorded_at)
        invalidate_trip(trip_id)
        publish_position(trip_id, {"type": "position", "trip_id": trip_id, "point_id": point_id,
                                   "latitude": lat, "longitude": lon, "recorded_at": iso(recorded_at)})
        return jsonify({"point_id": point_id}), 201
    finally:
        conn.close()


@app.route("/api/trips/<int:trip_id>/end", methods=["POST"])
def end_trip(trip_id):
    payload = request.get_json(silent=True) or {}
    try:
        ended_at = datetime.fromisoformat((payload.get("ended_at") or datetime.now(timezone.utc).isoformat()).replace("Z", "+00:00"))
        if ended_at.tzinfo is None:
            raise ValueError("timezone required")
    except (AttributeError, ValueError):
        return jsonify({"error": "ended_at must be an ISO 8601 timestamp with a timezone."}), 400
    conn = get_db_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT started_at, status FROM trips WHERE trip_id = %s FOR UPDATE", (trip_id,))
                trip = cur.fetchone()
                if not trip:
                    return jsonify({"error": "Trip not found"}), 404
                if trip["status"] == "completed":
                    return jsonify({"error": "Trip is already completed"}), 409
                cur.execute("SELECT MAX(recorded_at) AS latest FROM gps_points WHERE trip_id = %s", (trip_id,))
                latest = cur.fetchone()["latest"]
                if ended_at < trip["started_at"] or (latest and ended_at < latest):
                    return jsonify({"error": "ended_at must be after trip start and the last point."}), 400
                cur.execute("UPDATE trips SET ended_at = %s, status = 'completed' WHERE trip_id = %s", (ended_at, trip_id))
                refresh_trip_summary(cur, trip_id)
        invalidate_trip(trip_id)
        publish_position(trip_id, {"type": "completed", "trip_id": trip_id})
        return jsonify(fetch_trip_detail(trip_id))
    finally:
        conn.close()


# =========================
# CRUD + TRANSACTION + EXPLAIN DEMO HELPERS
# =========================

def validate_lat_lon(lat, lon):
    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError):
        return None, None, "Latitude and longitude must be numbers."
    if not (-90 <= lat <= 90):
        return None, None, "Latitude must be between -90 and 90."
    if not (-180 <= lon <= 180):
        return None, None, "Longitude must be between -180 and 180."
    return lat, lon, None


def validate_trip_payload(payload, require_points=True):
    if not isinstance(payload, dict):
        return "Provide a JSON object.", None
    required = ["user_id", "device_id", "started_at"]
    missing = [field for field in required if not payload.get(field)]
    if missing:
        return f"Missing fields: {', '.join(missing)}", None

    points = payload.get("points", [])
    if not isinstance(points, list) or (require_points and len(points) < 2):
        return "A trip needs at least two coordinate points.", None

    cleaned_points = []
    for index, point in enumerate(points, start=1):
        if not isinstance(point, dict):
            return f"Point {index} must be an object.", None
        lat, lon, error = validate_lat_lon(point.get("latitude"), point.get("longitude"))
        if error:
            return f"Point {index}: {error}", None
        recorded_at = point.get("recorded_at") or payload.get("started_at")
        cleaned_points.append({
            "latitude": lat,
            "longitude": lon,
            "recorded_at": recorded_at,
            "accuracy_m": point.get("accuracy_m"),
            "speed_kmh": point.get("speed_kmh"),
        })

    started_at = payload.get("started_at")
    ended_at = payload.get("ended_at") or None
    try:
        start_dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(ended_at.replace("Z", "+00:00")) if ended_at else None
        point_dts = [datetime.fromisoformat(p["recorded_at"].replace("Z", "+00:00")) for p in cleaned_points]
        if start_dt.tzinfo is None or (end_dt and end_dt.tzinfo is None) or any(p.tzinfo is None for p in point_dts):
            raise ValueError("timezone required")
        if (end_dt and end_dt < start_dt) or any(p < start_dt or (end_dt and p > end_dt) for p in point_dts):
            raise ValueError("point outside trip")
        if point_dts != sorted(point_dts) or len(set(point_dts)) != len(point_dts):
            raise ValueError("points not strictly ordered")
    except (AttributeError, ValueError):
        return "Timestamps must include a timezone, be ordered, and fall within the trip interval.", None
    status = "completed" if ended_at else "in_progress"

    return None, {
        "user_id": payload.get("user_id"),
        "device_id": payload.get("device_id"),
        "started_at": started_at,
        "ended_at": ended_at,
        "status": status,
        "points": cleaned_points,
    }


def insert_points(cur, trip_id, points):
    for point in points:
        cur.execute(
            """
            INSERT INTO gps_points
                (trip_id, latitude, longitude, recorded_at, accuracy_m, speed_kmh)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                trip_id,
                point["latitude"],
                point["longitude"],
                point["recorded_at"],
                point.get("accuracy_m"),
                point.get("speed_kmh"),
            ),
        )


@app.route("/api/trips", methods=["POST"])
def create_trip_with_points():
    payload = request.get_json(silent=True)
    error, data = validate_trip_payload(payload, require_points=True)
    if error:
        return jsonify({"error": error}), 400

    conn = get_db_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO trips (user_id, device_id, started_at, ended_at, status)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING trip_id
                    """,
                    (data["user_id"], data["device_id"], data["started_at"], data["ended_at"], data["status"]),
                )
                trip_id = cur.fetchone()["trip_id"]
                insert_points(cur, trip_id, data["points"])
                refresh_trip_summary(cur, trip_id)
        return jsonify(fetch_trip_detail(trip_id)), 201
    finally:
        conn.close()


@app.route("/api/trips/<int:trip_id>", methods=["PUT"])
def update_trip_with_points(trip_id):
    payload = request.get_json(silent=True)
    error, data = validate_trip_payload(payload, require_points=True)
    if error:
        return jsonify({"error": error}), 400

    conn = get_db_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE trips
                    SET user_id = %s,
                        device_id = %s,
                        started_at = %s,
                        ended_at = %s,
                        status = %s
                    WHERE trip_id = %s
                    RETURNING trip_id
                    """,
                    (data["user_id"], data["device_id"], data["started_at"], data["ended_at"], data["status"], trip_id),
                )
                if not cur.fetchone():
                    return jsonify({"error": "Trip not found"}), 404

                # Replace the route points for this trip. This lets update use the same UI fields as insert.
                cur.execute("DELETE FROM gps_points WHERE trip_id = %s", (trip_id,))
                insert_points(cur, trip_id, data["points"])
                refresh_trip_summary(cur, trip_id)
        invalidate_trip(trip_id)
        return jsonify(fetch_trip_detail(trip_id))
    finally:
        conn.close()


@app.route("/api/trips/<int:trip_id>", methods=["DELETE"])
def delete_trip(trip_id):
    conn = get_db_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM trips WHERE trip_id = %s RETURNING trip_id", (trip_id,))
                row = cur.fetchone()
                if not row:
                    return jsonify({"error": "Trip not found"}), 404
        invalidate_trip(trip_id)
        return jsonify({"message": f"Trip {trip_id} deleted. Related gps_points, summaries, stops, and geofence rows were removed by ON DELETE CASCADE."})
    finally:
        conn.close()

if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG") == "1")
