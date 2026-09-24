from datetime import datetime, timezone
from unittest.mock import MagicMock

import app as service


def test_trip_payload_rejects_out_of_order_or_outside_points():
    payload = {
        "user_id": 1,
        "device_id": 1,
        "started_at": "2026-03-24T08:00:00Z",
        "ended_at": "2026-03-24T09:00:00Z",
        "points": [
            {"latitude": 45.55, "longitude": -94.15, "recorded_at": "2026-03-24T08:10:00Z"},
            {"latitude": 45.56, "longitude": -94.16, "recorded_at": "2026-03-24T08:05:00Z"},
        ],
    }
    error, _ = service.validate_trip_payload(payload)
    assert "ordered" in error
    payload["points"][1]["recorded_at"] = "2026-03-24T09:05:00Z"
    error, _ = service.validate_trip_payload(payload)
    assert "interval" in error


def test_trip_detail_cache_aside_and_invalidation(monkeypatch):
    fake_cache = MagicMock()
    fake_cache.get.side_effect = [None, '{"trip":{"trip_id":7}}']
    monkeypatch.setattr(service, "cache", fake_cache)
    fetch = MagicMock(return_value={"trip": {"trip_id": 7}})
    monkeypatch.setattr(service, "fetch_trip_detail", fetch)
    assert service.cached_trip_detail(7)["trip"]["trip_id"] == 7
    assert service.cached_trip_detail(7)["trip"]["trip_id"] == 7
    fetch.assert_called_once_with(7)
    fake_cache.setex.assert_called_once()
    assert fake_cache.setex.call_args.args[1] == service.CACHE_TTL_SECONDS
    service.invalidate_trip(7)
    fake_cache.delete.assert_called_once_with("routepulse:trip:7")


def test_disabling_cache_serves_fresh_data(monkeypatch):
    fake_cache = MagicMock()
    monkeypatch.setattr(service, "cache", fake_cache)
    monkeypatch.setattr(service, "CACHE_ENABLED", False)
    fetch = MagicMock(return_value={"trip": {"trip_id": 7}})
    monkeypatch.setattr(service, "fetch_trip_detail", fetch)
    assert service.cached_trip_detail(7) == {"trip": {"trip_id": 7}}
    fake_cache.get.assert_not_called()
    fetch.assert_called_once_with(7)


def test_spatial_endpoint_validates_inputs_and_uses_indexable_predicate(monkeypatch):
    client = service.app.test_client()
    assert client.get("/api/nearby/points?lat=91&lon=0").status_code == 400
    fake_conn = MagicMock()
    cur = fake_conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = []
    monkeypatch.setattr(service, "get_db_connection", lambda: fake_conn)
    response = client.get("/api/nearby/points?lat=45.5&lon=-94.1&radius_m=500&limit=10")
    assert response.status_code == 200
    sql, params = cur.execute.call_args.args
    assert "ST_DWithin(location" in sql
    assert params == (-94.1, 45.5, -94.1, 45.5, 500.0, 10)
    fake_conn.close.assert_called_once()


def test_point_write_rejects_completed_trip_without_publishing(monkeypatch):
    fake_conn = MagicMock()
    cur = fake_conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = {"status": "completed", "started_at": datetime(2026, 3, 24, tzinfo=timezone.utc)}
    monkeypatch.setattr(service, "get_db_connection", lambda: fake_conn)
    published = MagicMock()
    monkeypatch.setattr(service, "publish_position", published)
    response = service.app.test_client().post("/api/trips/1/points", json={
        "latitude": 45.55, "longitude": -94.15, "recorded_at": "2026-03-24T08:01:00Z"
    })
    assert response.status_code == 409
    published.assert_not_called()


def test_point_write_updates_summary_invalidates_cache_and_publishes(monkeypatch):
    fake_conn = MagicMock()
    cur = fake_conn.cursor.return_value.__enter__.return_value
    start = datetime(2026, 3, 24, 8, 0, tzinfo=timezone.utc)
    cur.fetchone.side_effect = [
        {"status": "in_progress", "started_at": start},
        {"latest": None},
        {"point_id": 42},
        {"km": 0},
        {"recorded_at": start},
    ]
    monkeypatch.setattr(service, "get_db_connection", lambda: fake_conn)
    invalidated = MagicMock()
    published = MagicMock()
    monkeypatch.setattr(service, "invalidate_trip", invalidated)
    monkeypatch.setattr(service, "publish_position", published)
    response = service.app.test_client().post("/api/trips/1/points", json={
        "latitude": 45.55, "longitude": -94.15, "recorded_at": "2026-03-24T08:01:00Z"
    })
    assert response.status_code == 201
    assert response.json["point_id"] == 42
    assert any("UPDATE trip_summaries" in call.args[0] for call in cur.execute.call_args_list)
    invalidated.assert_called_once_with(1)
    assert published.call_args.args[1]["type"] == "position"


def test_metrics_and_liveness_do_not_require_database():
    client = service.app.test_client()
    assert client.get("/api/health/live").status_code == 200
    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert b"routepulse_http_requests_total" in metrics.data
