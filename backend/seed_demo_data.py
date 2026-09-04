"""Seed working demo data: trips, assigned routes, statuses, LNS runs, fleet telemetry.

Makes the Live Ops dashboard genuinely "alive". Runs inside the backend container
against the running API so every trip flows through the real pipeline
(POST /api/trips -> queue -> greedy worker -> route/stop creation + audit).

Usage:
    docker compose exec backend python seed_demo_data.py            # 40 trips
    docker compose exec backend python seed_demo_data.py --count 80

Leaves a realistic mix: 55% Delivered, 20% In-Transit (on route, moving),
20% Scheduled (future pickups), 5% unassigned (honest ~0 queue depth).
Also seeds realtime_fleet_status for in-flight vehicles and triggers two LNS
runs so optimization_runs is populated. Uses only stdlib + project models.
"""
import argparse
import json
import random
import time
import urllib.request
from datetime import datetime, timedelta, timezone

BASE = "http://127.0.0.1:8000/api"

# Hyderabad landmarks (all inside the service-area bounds).
LANDMARKS = [
    ("Hitech City", 17.4441, 78.3772), ("Gachibowli", 17.4401, 78.3481),
    ("Secunderabad", 17.4399, 78.4983), ("Kukatpally", 17.4860, 78.4015),
    ("Begumpet", 17.4439, 78.4661), ("Madhapur", 17.4484, 78.3915),
    ("Jubilee Hills", 17.4340, 78.4050), ("Uppal", 17.4050, 78.5630),
    ("LB Nagar", 17.3400, 78.5500), ("Mehdipatnam", 17.3950, 78.4350),
    ("Patancheru", 17.5300, 78.2640), ("Tolichowki", 17.3994, 78.4211),
    ("Koti", 17.3892, 78.4818), ("Amberpet", 17.4060, 78.5200),
    ("Shamshabad", 17.2400, 78.4300),
]


def _post(url: str, payload: dict) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())


def _get(url: str) -> list:
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.loads(r.read().decode())


def create_trips(count: int, now: datetime) -> None:
    """Create `count` trips through the API with a spread of pickup times."""
    for i in range(count):
        a, b = random.sample(LANDMARKS, 2)
        bucket = i / count
        if bucket < 0.55:           # delivered: pickup in the past
            pickup = now - timedelta(hours=5, minutes=i % 50)
        elif bucket < 0.75:         # in-transit: pickup ~30 min ago
            pickup = now - timedelta(minutes=30 + i % 20)
        else:                       # scheduled: pickup in the future
            pickup = now + timedelta(hours=2 + (i % 5))
        payload = {
            "origin": a[0], "destination": b[0],
            "gps_start_lat": a[1], "gps_start_lon": a[2],
            "gps_end_lat": b[1], "gps_end_lon": b[2],
            "load_weight_kg": 200 + (i * 137) % 1200,
            "vehicle_type": "Truck",
            "pickup_time": pickup.isoformat(),
            "planned_delivery_time": (pickup + timedelta(hours=2)).isoformat(),
            "planned_distance_km": 8 + ((i * 7) % 40),
        }
        try:
            _post(f"{BASE}/trips", payload)
        except Exception as e:
            print(f"[demo] create failed {a[0]}->{b[0]}: {e}")

def mark_statuses(now: datetime) -> None:
    """Assign a realistic status mix post-assignment + seed fleet telemetry."""
    from app.db.session import SessionLocal
    from app.models.trip import Trip
    from app.models.realtime_fleet_status import RealtimeFleetStatus

    db = SessionLocal()
    try:
        with_route = db.query(Trip).filter(Trip.route_id.isnot(None)).all()
        delivered = in_transit = scheduled = 0
        for i, t in enumerate(with_route):
            if i < len(with_route) * 0.55:
                t.status = "Delivered"
                t.actual_delivery_time = now - timedelta(hours=3)
                delivered += 1
            elif i < len(with_route) * 0.75:
                t.status = "In-Transit"
                t.actual_delivery_time = None
                in_transit += 1
            else:
                t.status = "Scheduled"
                scheduled += 1
            db.add(t)

        # Live-markers for in-flight vehicles so the map shows movement.
        # Only trips with a vehicle_id (greedy insertion into an existing route
        # leaves vehicle_id NULL; new-route creation sets it).
        active = (
            db.query(Trip)
            .filter(Trip.status == "In-Transit", Trip.vehicle_id.isnot(None))
            .limit(6).all()
        )
        for i, t in enumerate(active):
            db.merge(RealtimeFleetStatus(
                vehicle_id=t.vehicle_id, current_trip_id=t.trip_id,
                current_lat=t.gps_start_lat, current_lon=t.gps_start_lon,
                current_speed_kmph=30 + (i * 11) % 35, status="Active",
                last_updated=now,
            ))
        db.commit()
        print(f"[demo] statuses -> delivered={delivered} in_transit={in_transit} "
              f"scheduled={scheduled}; {len(active)} telemetry rows")
    finally:
        db.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=40)
    args = ap.parse_args()

    try:
        from seed_fleet import seed as seed_fleet
        seed_fleet()
    except ImportError:
        print("[demo] seed_fleet not available - ensure vehicles/drivers exist")

    now = datetime.now(timezone.utc)
    print(f"[demo] creating {args.count} trips through the API...")
    create_trips(args.count, now)

    print("[demo] waiting for the assignment worker...")
    deadline = time.time() + 120
    while time.time() < deadline:
        rows = _get(f"{BASE}/trips?limit=100")
        if len(rows) >= args.count and not [r for r in rows if not r.get("route_id")]:
            break
        time.sleep(5)
    rows = _get(f"{BASE}/trips?limit=200")
    queued = sum(1 for r in rows if not r.get("route_id"))
    print(f"[demo] assigned {len(rows) - queued}/{len(rows)} trips; queue depth {queued}")

    mark_statuses(now)

    for k in range(2):
        try:
            _post(f"{BASE}/routes/lns/trigger", {})
            print(f"[demo] LNS run {k + 1} queued")
        except Exception as e:
            print(f"[demo] LNS trigger failed: {e}")
    print("[demo] done.")


if __name__ == "__main__":
    main()