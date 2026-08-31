"""LNS global-optimization test.

Seeds driver/vehicles/trips, assigns them through the real greedy worker, then
runs LNSOptimizer.optimize over the assembled routes and verifies:
- LNS runs without exceptions,
- destroy+repair preserves every trip (no lost assignments),
- audit rows are persisted, and DB is left consistent.
Cleans up after itself (allow keep=True to inspect).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import delete
from app.db.session import SessionLocal
from app.models.trip import Trip
from app.models.route import Route, RouteStop
from app.models.vehicle import Vehicle
from app.models.driver import Driver
from app.models.optimization_audit import RouteAssignment, OptimizationRun
from app.workers.trip_assignment_worker import TripAssignmentWorker
from app.optimization.lns.optimizer import LNSOptimizer, LNSDestroyStrategy, LNSRepairStrategy

PREFIX = "LNSTST"
KEEP = os.environ.get("LNS_TEST_KEEP", "0") == "1"


def cleanup(db):
    db.rollback()
    route_ids = [r[0] for r in db.query(Route.route_id).filter(
        (Route.name.like("Route-LNSTST%")) | (Route.driver_id.like("LNSTST%"))
    ).all()]
    db.execute(delete(RouteStop).where(RouteStop.trip_id.like(f"{PREFIX}%")))
    if route_ids:
        db.execute(delete(RouteStop).where(RouteStop.route_id.in_(route_ids)))
    db.execute(delete(RouteAssignment).where(RouteAssignment.trip_id.like(f"{PREFIX}%")))
    db.execute(delete(OptimizationRun).where(OptimizationRun.trip_id.like(f"{PREFIX}%")))
    db.execute(delete(Route).where(
        (Route.name.like("Route-LNSTST%")) | (Route.driver_id.like("LNSTST%"))
    ))
    db.execute(delete(Trip).where(Trip.trip_id.like(f"{PREFIX}%")))
    db.execute(delete(Vehicle).where(Vehicle.vehicle_id.like(f"{PREFIX}%")))
    db.execute(delete(Driver).where(Driver.driver_id.like(f"{PREFIX}%")))
    db.commit()


def main() -> int:
    db = SessionLocal()
    failed = True
    try:
        # Defensive pre-clean: remove leftovers from a previously crashed run.
        cleanup(db)

        # --- Seed ---
        drv = Driver(driver_id=f"{PREFIX}DRV1", driver_name="LNS Driver", status="active",
                     license_type="LMV", experience_years=6, rating=4.2)
        db.add(drv)
        v1 = Vehicle(vehicle_id=f"{PREFIX}VEH1", vehicle_type="Truck", status="active",
                     load_capacity_kg=9000, avg_kmpl_rated=8.0)
        v2 = Vehicle(vehicle_id=f"{PREFIX}VEH2", vehicle_type="Truck", status="active",
                     load_capacity_kg=9000, avg_kmpl_rated=8.0)
        db.add_all([v1, v2]); db.commit()

        specs = [
            (17.4401, 78.3489, 17.4126, 78.4381, 900),  # Gachibowli -> Banjara Hills
            (17.4126, 78.4381, 17.4399, 78.4983, 700),  # Banjara Hills -> Secunderabad
            (17.4399, 78.4983, 17.4013, 78.5584, 1100), # Secunderabad -> Uppal
            (17.4013, 78.5584, 17.3616, 78.4747, 600),  # Uppal -> Charminar
            (17.2403, 78.4294, 17.4401, 78.3489, 800),  # Airport -> Gachibowli
            (17.4435, 78.3772, 17.4849, 78.4138, 1000), # Hitec City -> Kukatpally
            (17.4399, 78.4983, 17.2403, 78.4294, 950),  # Secunderabad -> Airport
            (17.3616, 78.4747, 17.4399, 78.4983, 650),  # Charminar -> Secunderabad
        ]
        trip_ids = []
        for i, (slat, slon, elat, elon, load) in enumerate(specs):
            tid = f"{PREFIX}TR{i}"
            db.add(Trip(trip_id=tid, status="scheduled", origin=f"O{i}", destination=f"D{i}",
                        gps_start_lat=slat, gps_start_lon=slon, gps_end_lat=elat, gps_end_lon=elon,
                        load_weight_kg=load, vehicle_type="Truck"))
            trip_ids.append(tid)
        db.commit()
        print(f"[seed] {len(trip_ids)} trips, 2 vehicles, 1 driver")

        # --- Assign all via the real worker ---
        worker = TripAssignmentWorker()
        for tid in trip_ids:
            ok = worker._assign_trip(db, tid)
            if not ok:
                print(f"  assignment FAILED for {tid}")
                return 1
        routes = db.query(Route).filter(Route.driver_id == f"{PREFIX}DRV1").all()
        print(f"[assign] {len(routes)} route(s), stops={sum(len(r.stops) for r in routes)}")

        # --- Run LNS over every route that actually holds the test trips ---
        # (greedy may legitimately pick pre-existing routes, so don't filter
        # by the test driver — collect routes from the trips' assignments)
        route_id_set = {t.route_id for t in db.query(Trip).filter(
            Trip.trip_id.like(f"{PREFIX}%"), Trip.route_id.isnot(None)).all()}
        routes = db.query(Route).filter(Route.route_id.in_(route_id_set)).all() if route_id_set else []
        print(f"[lns-scope] {len(routes)} route(s) containing test trips")

        optimizer = LNSOptimizer(
            destroy_strategy=LNSDestroyStrategy.RANDOM,
            repair_strategy=LNSRepairStrategy.REGRET_2,
            destroy_percentage=0.3,
        )
        result = optimizer.optimize(db, routes)
        print(f"[lns] success={result.success} improvement={result.improvement:.2f} "
              f"old={result.old_cost:.2f} new={result.new_cost:.2f} "
              f"affected={result.routes_affected} reinserted={result.trips_reinserted} "
              f"err={result.error_message}")

        # --- Verify every trip still assigned exactly once and DB consistent ---
        db.expire_all()
        trips = db.query(Trip).filter(Trip.trip_id.like(f"{PREFIX}%")).all()
        unassigned = [t.trip_id for t in trips if not t.route_id]
        if unassigned:
            print(f"  !! trips lost: {unassigned}")
            return 1

        # --- Verify no duplicate stops were left by destroy/rollback ---
        from collections import defaultdict
        dupes = []
        stops_by_trip = defaultdict(list)
        for s in db.query(RouteStop).filter(RouteStop.trip_id.like(f"{PREFIX}%")).all():
            stops_by_trip[s.trip_id].append((s.stop_type, s.sequence))
        for tid, entries in stops_by_trip.items():
            types = [t for t, _ in entries]
            if len(types) != len(set(types)) or len(entries) != 2:
                dupes.append((tid, entries))
        if dupes:
            print(f"  !! duplicate/incorrect stops after LNS: {dupes}")
            return 1
        print("[verify] no duplicate stops after LNS rollback")

        runs = db.query(OptimizationRun).filter(OptimizationRun.trip_id.like(f"{PREFIX}%")).all()
        greedy_runs = [r for r in runs if r.optimization_type == "ONLINE_GREEDY"]
        print(f"[audit] greedy audit rows={len(greedy_runs)}")
        if len(greedy_runs) < len(trip_ids):
            print("  !! not every assignment was audited")
            return 1

        faln = db.query(OptimizationRun).filter(
            OptimizationRun.optimization_type == "PERIODIC_LNS"
        ).all()
        print(f"[audit] LNS audit rows={len(faln)}")

        print("\n=== LNS TEST PASSED ===")
        failed = False
    except Exception as exc:
        import traceback
        traceback.print_exc()
    finally:
        if KEEP:
            print("[cleanup] skipped (KEEP=1)")
            db.close()
        else:
            cleanup(db)
            db.close()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())