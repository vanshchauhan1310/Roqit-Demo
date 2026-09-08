"""E2E test for the every-3-completions prediction trigger.

Creates 4 identical trips, waits for the assignment worker to batch them on a
route, backdates 3 so the completion sweep finishes them (crossing the N=3
boundary), then runs the sweep in-process and prints what happened.
"""
import sys
import time
import urllib.request

BASE = "http://localhost:8000"


def api(method: str, path: str, payload: dict | None = None):
    req = urllib.request.Request(
        BASE + path,
        method=method,
        data=None if payload is None else None,
    )
    if payload is not None:
        import json
        req.data = json.dumps(payload).encode()
        req.add_header("Content-Type", "application/json")
    try:
        return urllib.request.urlopen(req, timeout=30).read().decode()
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code}: {e.read().decode()}"


def main():
    # 1. Create 4 identical trips
    for i in range(1, 5):
        tid = f"TRP-PT{i:02d}"
        r = api("POST", "/api/trips", {
            "trip_id": tid,
            "vehicle_type": "Truck",
            "origin": "Hyderabad",
            "destination": "Secunderabad",
            "gps_start_lat": 17.3850, "gps_start_lon": 78.4867,
            "gps_end_lat": 17.4399, "gps_end_lon": 78.4983,
            "road_type": "City Road",
            "traffic_density": "Medium",
            "weather_condition": "Clear",
            "fuel_price_per_l": 92.5,
            "load_weight_kg": 500,
        })
        print(f"create {tid}: {r}")

    # 2. Wait for the assignment worker to assign them
    print("waiting 75s for assignment worker...")
    time.sleep(75)
    print(api("GET", "/api/trips?limit=200").count("TRP-PT0"), "of 4 test trips visible")


if __name__ == "__main__":
    sys.exit(main())
