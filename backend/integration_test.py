"""End-to-end integration test of the real-time dynamic optimization engine.

Seeds minimal test data (driver, vehicles, trips) in the live DB, then drives
the *actual* greedy insertion pipeline exactly as the TripAssignmentWorker
would, capturing every failure. Cleans up after itself.
"""
import os
import sys
import time
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import delete
from app.db.session import SessionLocal
from app.models.trip import Trip
from app.models.route import Route, RouteStop
from app.models.vehicle import Vehicle
from app.models.driver import Driver
from app.models.optimization_audit import RouteAssignment, OptimizationRun
from app.workers.trip_assignment_worker import TripAssignmentWorker
from app.optimization.greedy.insertion import greedy_insertion

PREFIX = "TST"
CREATED = {"drivers": [], "vehicles": [], "trips": [], "routes": []}


def cleanup(db):
    # Roll back any pending writes from a failed assignment attempt first.
    db.rollback()
    # Delete in FK dependency order, matching any rows the test created.
    # Note: worker-created routes are named "Route-TST...", so match both.
    route_ids = [r[0] for r in db.query(Route.route_id).filter(
        (Route.name.like("Route-TST%")) | (Route.driver_id.like("TST%"))
    ).all()]
    # RouteStops referenced by test trips (covers stops left on any route
    # from a previous crashed run, not just routes created by this run).
    db.execute(delete(RouteStop).where(RouteStop.trip_id.like(f"{PREFIX}%")))
    if route_ids:
        db.execute(delete(RouteStop).where(RouteStop.route_id.in_(route_ids)))
    db.execute(delete(RouteAssignment).where(RouteAssignment.trip_id.like(f"{PREFIX}%")))
    db.execute(delete(OptimizationRun).where(OptimizationRun.trip_id.like(f"{PREFIX}%")))
    db.execute(delete(Route).where(
        (Route.name.like("Route-TST%")) | (Route.driver_id.like("TST%"))
    ))
    db.execute(delete(Trip).where(Trip.trip_id.like(f"{PREFIX}%")))
    db.execute(delete(Vehicle).where(Vehicle.vehicle_id.like(f"{PREFIX}%")))
    db.execute(delete(Driver).where(Driver.driver_id.like(f"{PREFIX}%")))
    db.commit()


def main():
    db = SessionLocal()
    failed = False
    try:
        # Defensive pre-clean: remove leftovers from a previously crashed run.
        cleanup(db)

        # --- Seed a driver and two vehicles ---
        drv = Driver(driver_id=f"{PREFIX}DRV1", driver_name="Test Driver", status="active",
                     license_type="LMV", experience_years=5, rating=4.5)
        db.add(drv); db.commit(); db.refresh(drv)
        CREATED["drivers"].append(drv.driver_id)
        print("[seed] driver", drv.driver_id)

        v1 = Vehicle(vehicle_id=f"{PREFIX}VEH1", vehicle_type="Truck", status="active",
                     load_capacity_kg=5000, avg_kmpl_rated=8.5)
        v2 = Vehicle(vehicle_id=f"{PREFIX}VEH2", vehicle_type="Truck", status="active",
                     load_capacity_kg=8000, avg_kmpl_rated=9.0)
        db.add_all([v1, v2]); db.commit()
        CREATED["vehicles"].extend([v1.vehicle_id, v2.vehicle_id])
        print("[seed] vehicles", v1.vehicle_id, v2.vehicle_id)

        # --- Define trips around Hyderabad (close together) ---
        trip_specs = [
            ("GCB", 17.4401, 78.3489, 17.4126, 78.4381, 800),  # Gachibowli->Banjara Hills
            ("BJH", 17.4126, 78.4381, 17.4399, 78.4983, 900),  # Banjara Hills->Secunderabad
            ("SCD", 17.4399, 78.4983, 17.4013, 78.5584, 1200), # Secunderabad->Uppal
            ("UPP", 17.4013, 78.5584, 17.3616, 78.4747, 700),  # Uppal->Charminar
        ]
        trip_ids = []
        for i, (name, slat, slon, elat, elon, load) in enumerate(trip_specs):
            tid = f"{PREFIX}TRIP{i}_{name}"
            trip = Trip(
                trip_id=tid, status="scheduled", origin=name, destination=name,
                gps_start_lat=slat, gps_start_lon=slon, gps_end_lat=elat, gps_end_lon=elon,
                load_weight_kg=load, vehicle_type="Truck", weather_condition="Clear",
                road_type="Highway", traffic_density="Low",
            )
            db.add(trip)
            trip_ids.append(tid)
        db.commit()
        CREATED["trips"].extend(trip_ids)
        print("[seed] trips", trip_ids)

        # --- Drive the actual assignment pipeline per trip ---
        worker = TripAssignmentWorker()
        print("\n=== DRIVING ACTUAL ASSIGNMENT PIPELINE ===")
        for tid in trip_ids:
            st = time.time()
            ok = worker._assign_trip(db, tid)
            ms = (time.time() - st) * 1000
            t = db.get(Trip, tid)
            route_id = t.route_id if t else None
            print(f"  trip {tid}: ok={ok} route_id={route_id} latency={ms:.1f}ms")
            if not ok:
                failed = True

        # --- Report final state ---
        print("\n=== FINAL STATE ===")
        routes = db.query(Route).all()
        print(f"  total routes: {len(routes)}")
        for r in routes:
            stops = sorted(r.stops, key=lambda s: s.sequence)
            print(f"  route {r.route_id} status={r.status} vehicle={r.vehicle_id} stops={len(stops)}")
            for s in stops:
                print(f"      seq={s.sequence} {s.stop_type} trip={s.trip_id}")

    except Exception as e:
        import traceback
        traceback.print_exc()
        failed = True
    finally:
        cleanup(db)
        db.close()

    print("\n=== RESULT:", "FAILED" if failed else "PASSED", "===")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
