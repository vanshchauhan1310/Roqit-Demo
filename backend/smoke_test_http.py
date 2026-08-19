"""HTTP-level smoke test for the new Trip & Route endpoints."""
import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

created_trip_ids = []
created_route_ids = []

try:
    # 1) POST /api/trips — minimal payload, no driver/vehicle/pickup_time
    resp = client.post("/api/trips", json={
        "origin": "Rotterdam, Maasvlakte Terminal 4",
        "destination": "Utrecht, City Center Warehouse",
        "gps_start_lat": 51.9544,
        "gps_start_lon": 4.1241,
        "gps_end_lat": 52.0907,
        "gps_end_lon": 5.1214,
        "planned_distance_km": 58.0,
    })
    assert resp.status_code == 201, f"create trip 1: {resp.status_code} {resp.text}"
    t1 = resp.json()
    assert t1["driver_id"] is None and t1["pickup_time"] is None and t1["status"] == "scheduled"
    created_trip_ids.append(t1["trip_id"])
    print(f"POST /api/trips minimal payload: OK -> {t1['trip_id']}")

    resp = client.post("/api/trips", json={
        "origin": "Utrecht, City Center Warehouse",
        "destination": "Amsterdam, Zuidas",
        "gps_start_lat": 52.0907,
        "gps_start_lon": 5.1214,
        "gps_end_lat": 52.3091,
        "gps_end_lon": 4.8933,
        "planned_distance_km": 42.0,
    })
    assert resp.status_code == 201, f"create trip 2: {resp.status_code} {resp.text}"
    t2 = resp.json()
    created_trip_ids.append(t2["trip_id"])
    print(f"POST /api/trips (2nd): OK -> {t2['trip_id']}")

    # 2) GET /api/trips?unassigned=true
    resp = client.get("/api/trips", params={"unassigned": "true"})
    assert resp.status_code == 200
    ids = {t["trip_id"] for t in resp.json()}
    assert t1["trip_id"] in ids and t2["trip_id"] in ids
    print("GET /api/trips?unassigned=true: OK")

    # 3) POST /api/routes/assign
    resp = client.post("/api/routes/assign", json={
        "trip_ids": [t1["trip_id"], t2["trip_id"]],
        "driver_id": "DRV001",
        "vehicle_id": "VEH001",
        "pickup_time": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
        "name": "HTTP smoke route",
        "loads": [
            {"trip_id": t1["trip_id"], "load_weight_kg": 8000, "load_value": 250000},
            {"trip_id": t2["trip_id"], "load_weight_kg": 5000, "load_value": 150000},
        ],
    })
    assert resp.status_code == 201, f"assign: {resp.status_code} {resp.text}"
    route = resp.json()
    created_route_ids.append(route["route_id"])
    assert len(route["stops"]) == 4
    assert all(s["trip_id"] is not None for s in route["stops"])
    assert route["driver_id"] == "DRV001" and route["vehicle_id"] == "VEH001"
    print(f"POST /api/routes/assign: OK -> {route['route_id']} ({len(route['stops'])} stops)")

    # 4) PATCH /api/routes/{id}/stops/reorder — legal order
    stops = sorted(route["stops"], key=lambda s: s["sequence"])
    t1_pickup = next(s for s in stops if s["trip_id"] == t1["trip_id"] and s["stop_type"] == "pickup")
    t1_drop = next(s for s in stops if s["trip_id"] == t1["trip_id"] and s["stop_type"] == "delivery")
    t2_pickup = next(s for s in stops if s["trip_id"] == t2["trip_id"] and s["stop_type"] == "pickup")
    t2_drop = next(s for s in stops if s["trip_id"] == t2["trip_id"] and s["stop_type"] == "delivery")

    resp = client.patch(f"/api/routes/{route['route_id']}/stops/reorder",
                        json={"stop_ids": [t1_pickup["stop_id"], t1_drop["stop_id"], t2_pickup["stop_id"], t2_drop["stop_id"]]})
    assert resp.status_code == 200, f"reorder: {resp.status_code} {resp.text}"
    print("PATCH reorder (legal): OK")

    # 5) PATCH reorder — illegal (t2 delivery before t2 pickup) -> 400
    resp = client.patch(f"/api/routes/{route['route_id']}/stops/reorder",
                        json={"stop_ids": [t1_pickup["stop_id"], t2_drop["stop_id"], t1_drop["stop_id"], t2_pickup["stop_id"]]})
    assert resp.status_code == 400, f"illegal reorder: {resp.status_code} {resp.text}"
    assert "TRP" in resp.json()["detail"] or "Precedence" in resp.json()["detail"], resp.text
    print("PATCH reorder (illegal) -> 400: OK")

    # 6) POST /api/routes/assign with 1 trip -> 400
    resp = client.post("/api/routes/assign", json={
        "trip_ids": [t1["trip_id"]],
        "driver_id": "DRV001",
        "vehicle_id": "VEH001",
        "pickup_time": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
    })
    assert resp.status_code == 400, f"single trip: {resp.status_code} {resp.text}"
    print("POST /api/routes/assign (1 trip) -> 400: OK")

    # 7) Over-capacity route -> 422
    resp = client.post("/api/routes/assign", json={
        "trip_ids": [t1["trip_id"], t2["trip_id"]],
        "driver_id": "DRV001",
        "vehicle_id": "VEH001",
        "pickup_time": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
        "loads": [
            {"trip_id": t1["trip_id"], "load_weight_kg": 10000},
            {"trip_id": t2["trip_id"], "load_weight_kg": 10000},
        ],
    })
    assert resp.status_code == 422, f"over-capacity: {resp.status_code} {resp.text}"
    print("POST /api/routes/assign (over capacity) -> 422: OK")

    print("\nALL HTTP SMOKE TESTS PASSED")
finally:
    from sqlalchemy import delete
    from app.db.session import SessionLocal
    from app.models.route import Route, RouteStop
    from app.models.trip import Trip

    db = SessionLocal()
    try:
        for rid in created_route_ids:
            db.execute(delete(RouteStop).where(RouteStop.route_id == rid))
            db.execute(delete(Route).where(Route.route_id == rid))
        for tid in created_trip_ids:
            db.execute(delete(Trip).where(Trip.trip_id == tid))
        db.commit()
    finally:
        db.close()
    print("Cleanup done")