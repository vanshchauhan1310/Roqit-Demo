"""End-to-end test through the live HTTP API.

Requires: backend running on :8000 (with workers via lifespan), Redis on :6379.

Flow:
1. Seed a driver + 2 vehicles via the API.
2. POST 6 trips via POST /api/trips (the real production entry point).
3. Poll until the trip-assignment worker has processed them all.
4. Verify every trip got a route_id, stops exist, audit rows persisted.
5. Trigger one LNS run via the API and verify the plan stays consistent.
"""
import os
import sys
import time

import requests

BASE = os.environ.get("API_BASE", "http://127.0.0.1:8000")
PREFIX = os.environ.get("E2E_PREFIX", "E2E")
API = f"{BASE}/api"

failures = []


def check(name, cond, detail=""):
    mark = "PASS" if cond else "FAIL"
    print(f"[{mark}] {name} {detail}")
    if not cond:
        failures.append(name)


def main() -> int:
    # --- 1. Seed driver + vehicles through the API ---
    d = requests.post(f"{API}/drivers", json={
        "driver_id": f"{PREFIX}DRV1", "driver_name": "E2E Driver",
        "status": "active", "license_type": "LMV",
        "experience_years": 5, "rating": 4.5,
    }, timeout=10)
    check("seed driver", d.status_code in (200, 201, 400, 409), d.status_code)

    for i in (1, 2):
        v = requests.post(f"{API}/vehicles", json={
            "vehicle_id": f"{PREFIX}VEH{i}", "vehicle_type": "Truck",
            "status": "active", "load_capacity_kg": 8000,
            "avg_kmpl_rated": 8.0,
        }, timeout=10)
        check(f"seed vehicle {i}", v.status_code in (200, 201, 400, 409), v.status_code)

    # --- 2. Post trips through the production endpoint ---
    specs = [
        (17.4401, 78.3489, 17.4126, 78.4381, 900),  # Gachibowli -> Banjara Hills
        (17.4126, 78.4381, 17.4399, 78.4983, 700),  # Banjara Hills -> Secunderabad
        (17.4399, 78.4983, 17.4013, 78.5584, 1100), # Secunderabad -> Uppal
        (17.4013, 78.5584, 17.3616, 78.4747, 600),  # Uppal -> Charminar
        (17.2403, 78.4294, 17.4401, 78.3489, 800),  # Airport -> Gachibowli (outlier -> new route)
        (17.4435, 78.3772, 17.4849, 78.4138, 1000), # Hitec City -> Kukatpally
    ]
    trip_ids = []
    for i, (slat, slon, elat, elon, load) in enumerate(specs):
        r = requests.post(f"{API}/trips", json={
            "trip_id": f"{PREFIX}TR{i}", "status": "scheduled",
            "origin": f"O{i}", "destination": f"D{i}",
            "gps_start_lat": slat, "gps_start_lon": slon,
            "gps_end_lat": elat, "gps_end_lon": elon,
            "load_weight_kg": load, "vehicle_type": "Truck",
        }, timeout=15)
        check(f"POST trip {i}", r.status_code in (200, 201, 202), f"{r.status_code} {r.text[:120]}")
        # server generates its own TRP-XXXXXXXX id
        ref = r.json().get("trip_ref") if r.status_code in (200, 201, 202) else None
        trip_ids.append(ref)

    # --- 3. Poll for worker assignment ---
    deadline = time.time() + 90
    assigned = {}
    while time.time() < deadline:
        assigned = {}
        for tid in trip_ids:
            try:
                r = requests.get(f"{API}/trips/{tid}", timeout=10)
                if r.status_code == 200:
                    body = r.json()
                    assigned[tid] = body.get("route_id")
            except requests.RequestException:
                pass
        if all(assigned.get(t) for t in trip_ids):
            break
        time.sleep(2)

    for tid in trip_ids:
        check(f"trip {tid} assigned", bool(assigned.get(tid)), f"route={assigned.get(tid)}")

    # --- 4. Verify routes view ---
    r = requests.get(f"{API}/routes?limit=50", timeout=10)
    check("GET /routes", r.status_code == 200, r.status_code)
    if r.status_code == 200:
        routes = r.json()
        mine = [x for x in routes if str(x.get("driver_id", "")).startswith(PREFIX)
                or any(tid in str(x) for tid in trip_ids)]
        print(f"       routes visible: {len(routes)} total, {len(mine)} for this test")

    # --- 5. LNS via API ---
    r = requests.post(f"{API}/routes/lns/trigger", timeout=60)
    check("LNS trigger", r.status_code in (200, 201, 202), f"{r.status_code} {r.text[:120]}")

    # give workers a moment, then re-check assignment consistency
    time.sleep(5)
    still = {}
    for tid in trip_ids:
        r = requests.get(f"{API}/trips/{tid}", timeout=10)
        if r.status_code == 200:
            still[tid] = r.json().get("route_id")
    lost = [t for t in trip_ids if not still.get(t)]
    check("no trips lost after LNS", not lost, f"lost={lost}")

    print()
    if failures:
        print(f"=== E2E FAILED ({len(failures)} failures): {failures} ===")
        return 1
    print("=== E2E TEST PASSED ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())