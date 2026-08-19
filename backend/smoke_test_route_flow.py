"""Smoke test for the Trip & Route creation flow against the real DB.

Creates 2 trips, assigns them to a route, reorders stops, verifies
precedence enforcement, then cleans up everything it created.
"""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from app.db.session import SessionLocal
from app.models.route import Route, RouteStop
from app.models.trip import Trip
from app.schemas.route import RouteAssignRequest, TripLoadInput
from app.schemas.trip import TripCreate
from app.services import route_service, trip_service

CREATED_TRIP_IDS: list[str] = []
CREATED_ROUTE_IDS: list[uuid.UUID] = []


async def main() -> None:
    db = SessionLocal()
    try:
        # 1) Create two trips without driver/vehicle/pickup_time
        t1 = await trip_service.create_trip(
            db,
            TripCreate(
                origin="Rotterdam, Maasvlakte Terminal 4",
                destination="Utrecht, City Center Warehouse",
                gps_start_lat=51.9544,
                gps_start_lon=4.1241,
                gps_end_lat=52.0907,
                gps_end_lon=5.1214,
                planned_distance_km=58.0,
            ),
        )
        t2 = await trip_service.create_trip(
            db,
            TripCreate(
                origin="Utrecht, City Center Warehouse",
                destination="Amsterdam, Zuidas",
                gps_start_lat=52.0907,
                gps_start_lon=5.1214,
                gps_end_lat=52.3091,
                gps_end_lon=4.8933,
                planned_distance_km=42.0,
            ),
        )
        CREATED_TRIP_IDS.extend([t1.trip_id, t2.trip_id])
        print(f"Created trips: {t1.trip_id} (driver_id={t1.driver_id}, pickup_time={t1.pickup_time}), {t2.trip_id}")
        assert t1.driver_id is None and t1.vehicle_id is None and t1.pickup_time is None
        assert t1.status == "scheduled"

        # 2) Unassigned list contains them
        unassigned = trip_service.list_unassigned_trips(db)
        unassigned_ids = {t.trip_id for t in unassigned}
        assert t1.trip_id in unassigned_ids and t2.trip_id in unassigned_ids
        print(f"Unassigned trips includes both: OK ({len(unassigned)} unassigned total)")

        # 3) Assign both to a route with a driver + vehicle + loads
        route = route_service.assign_route(
            db,
            RouteAssignRequest(
                trip_ids=[t1.trip_id, t2.trip_id],
                driver_id="DRV001",
                vehicle_id="VEH001",
                pickup_time=datetime.now(timezone.utc) + timedelta(hours=2),
                name="Smoke test route",
                loads=[
                    TripLoadInput(trip_id=t1.trip_id, load_weight_kg=8000, load_value=250000),
                    TripLoadInput(trip_id=t2.trip_id, load_weight_kg=5000, load_value=150000),
                ],
            ),
        )
        CREATED_ROUTE_IDS.append(route.route_id)
        print(f"Created route: {route.route_id} with {len(route.stops)} stops")

        # 4) Verify stop sequence: [A-pickup, B-pickup, A-drop, B-drop]
        stops = sorted(route.stops, key=lambda s: s.sequence)
        expected = [
            (t1.trip_id, "pickup"),
            (t2.trip_id, "pickup"),
            (t1.trip_id, "delivery"),
            (t2.trip_id, "delivery"),
        ]
        actual = [(s.trip_id, s.stop_type) for s in stops]
        assert actual == expected, f"Expected {expected}, got {actual}"
        print("Default stop order: OK")

        # 5) Trips denormalized: driver/vehicle/pickup_time + load written
        db.refresh(t1)
        db.refresh(t2)
        assert t1.driver_id == "DRV001" and t1.vehicle_id == "VEH001"
        assert t1.load_weight_kg == 8000 and t2.load_weight_kg == 5000
        assert t1.pickup_time is not None
        print("Trip denormalization + loads: OK")

        # 6) Trips no longer unassigned
        unassigned2 = {t.trip_id for t in trip_service.list_unassigned_trips(db)}
        assert t1.trip_id not in unassigned2 and t2.trip_id not in unassigned2
        print("Assigned trips leave unassigned list: OK")

        # 7) Reorder to [A-pickup, A-drop, B-pickup, B-drop] — legal
        by_type = {s.stop_type: s.stop_id for s in route.stops if s.trip_id == t1.trip_id}
        by_type_b = {s.stop_type: s.stop_id for s in route.stops if s.trip_id == t2.trip_id}
        legal_order = [by_type["pickup"], by_type["delivery"], by_type_b["pickup"], by_type_b["delivery"]]
        reordered = route_service.reorder_stops(db, route, legal_order)
        seq_map = {s.stop_id: s.sequence for s in reordered.stops}
        assert seq_map[by_type["pickup"]] == 1 and seq_map[by_type["delivery"]] == 2
        print("Legal reorder: OK")

        # 8) Illegal reorder — B's delivery before B's pickup must raise
        illegal_order = [by_type["pickup"], by_type_b["delivery"], by_type["delivery"], by_type_b["pickup"]]
        try:
            route_service.reorder_stops(db, route, illegal_order)
            raise AssertionError("PrecedenceViolationError was not raised!")
        except route_service.PrecedenceViolationError as exc:
            assert exc.trip_id == t2.trip_id
            print(f"Illegal reorder rejected: OK (PrecedenceViolationError, trip {exc.trip_id})")

        # 9) Stop set mismatch rejected
        try:
            route_service.reorder_stops(db, route, legal_order[:-1])
            raise AssertionError("StopSetMismatchError was not raised!")
        except route_service.StopSetMismatchError:
            print("Stop set mismatch rejected: OK")

        # 10) Insufficient trips rejected
        try:
            route_service.assign_route(
                db,
                RouteAssignRequest(
                    trip_ids=[t1.trip_id],
                    driver_id="DRV001",
                    vehicle_id="VEH001",
                    pickup_time=datetime.now(timezone.utc),
                ),
            )
            raise AssertionError("InsufficientTripsError was not raised!")
        except route_service.InsufficientTripsError:
            print("Single-trip route rejected: OK")

        print("\nALL SMOKE TESTS PASSED")
    finally:
        # Cleanup: delete route stops, route, and trips created by this test
        for route_id in CREATED_ROUTE_IDS:
            db.execute(delete(RouteStop).where(RouteStop.route_id == route_id))
            db.execute(delete(Route).where(Route.route_id == route_id))
        for trip_id in CREATED_TRIP_IDS:
            db.execute(delete(Trip).where(Trip.trip_id == trip_id))
        db.commit()
        db.close()
        print("Cleanup done")


asyncio.run(main())
