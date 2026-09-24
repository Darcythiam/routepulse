"""End-to-end smoke test against a disposable running Compose stack."""

import argparse
from datetime import datetime, timedelta, timezone
import json
from urllib.request import Request, urlopen

from simple_websocket import Client


def call(base, path, method="GET", body=None):
    request = Request(base + path, method=method,
                      data=json.dumps(body).encode() if body is not None else None,
                      headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=10) as response:
        return response.status, json.load(response)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:5000")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    assert call(base, "/api/health/ready")[0] == 200
    start = datetime.now(timezone.utc).replace(microsecond=0)
    status, trip = call(base, "/api/trips/start", "POST", {
        "user_id": 1, "device_id": 1, "started_at": start.isoformat()
    })
    assert status == 201
    trip_id = trip["trip_id"]
    ws = None
    try:
        ws_url = base.replace("https://", "wss://").replace("http://", "ws://")
        ws = Client.connect(f"{ws_url}/ws/trips/{trip_id}")
        assert json.loads(ws.receive(timeout=5))["type"] == "subscribed"
        for i in (1, 2):
            timestamp = (start + timedelta(seconds=i)).isoformat()
            status, point = call(base, f"/api/trips/{trip_id}/points", "POST", {
                "latitude": 45.553 + i / 10000,
                "longitude": -94.154 + i / 10000,
                "recorded_at": timestamp,
            })
            assert status == 201
            event = json.loads(ws.receive(timeout=5))
            assert event["type"] == "position" and event["point_id"] == point["point_id"]
        status, detail = call(base, f"/api/trips/{trip_id}")
        assert status == 200 and len(detail["points"]) == 2
        assert detail["trip"]["point_count"] == 2
        status, nearby = call(base, "/api/nearby/points?lat=45.553&lon=-94.154&radius_m=100")
        assert status == 200 and any(p["trip_id"] == trip_id for p in nearby)
        status, completed = call(base, f"/api/trips/{trip_id}/end", "POST", {
            "ended_at": (start + timedelta(seconds=3)).isoformat()
        })
        assert status == 200 and completed["trip"]["status"] == "completed"
        assert json.loads(ws.receive(timeout=5))["type"] == "completed"
        print(f"Smoke test passed: trip {trip_id}, spatial query, cache invalidation, WebSocket")
    finally:
        if ws:
            ws.close()
        call(base, f"/api/trips/{trip_id}", "DELETE")


if __name__ == "__main__":
    main()
