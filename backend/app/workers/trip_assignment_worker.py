"""Trip Assignment Worker - processes incoming trips and assigns them to routes."""

import uuid
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import or_, func
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.trip import Trip
from app.models.route import Route, RouteStop
from app.models.vehicle import Vehicle
from app.optimization.greedy.insertion import greedy_insertion, GreedyResult
from app.optimization.candidates.search import candidate_search
from app.optimization.audit.logger import audit_logger
from app.optimization.state import (
    AVG_ROUTE_SPEED_KPH,
    MAX_DRIVER_HOS_HOURS,
    SERVICE_HOURS_PER_STOP,
    TripAssignmentStatus,
    duty_window_start,
    estimate_route_hours,
    estimate_trip_hours,
    repair_trip_assignment,
    validate_trip_assignment,
    vehicle_active_load_kg,
)
from app.infrastructure.queue import Queue, QueueJob, get_queue
from app.optimization.state import acquire_writer_lock


class TripAssignmentWorker:
    """Worker that processes trip assignment jobs from the queue."""

    def __init__(self):
        self.queue = get_queue()

    def handle_job(self, job: QueueJob) -> bool:
        """Handle a trip assignment job.

        Returns True if successful, False if should retry.
        """
        trip_id = job.payload.get("trip_id")
        if not trip_id:
            print(f"Invalid job payload: {job.payload}")
            return False

        print(f"Processing trip assignment for {trip_id}")

        db = SessionLocal()
        try:
            # Writer funnel lock: serialize with the LNS optimizer and the
            # trip-completion worker so we can never deadlock with them over
            # route/trip row locks (see state.acquire_writer_lock).
            # Wait up to 75s (just past the LNS run budget) so a job that
            # lands mid-LNS *queues behind it and proceeds* instead of
            # failing + requeueing and burning attempts every cycle.
            if not acquire_writer_lock(db, lock_timeout_s=75):
                print(f"Trip {trip_id}: writer lock busy, deferring job")
                return False  # retry the job later
            return self._assign_trip(db, trip_id)
        except Exception as e:
            print(f"Error assigning trip {trip_id}: {e}")
            return False
        finally:
            db.close()

    def _assign_trip(self, db: Session, trip_id: str) -> bool:
        """Assign a trip using greedy best insertion."""
        trip = db.get(Trip, trip_id)
        if not trip:
            print(f"Trip {trip_id} not found")
            return False

        # Check if already assigned - using the canonical assignment-state
        # validator, never blindly trusting a non-null route_id (a trip can
        # carry a route_id to a deleted route, or lack a matching RouteStop).
        if trip.route_id:
            status = validate_trip_assignment(db, trip)
            if status == TripAssignmentStatus.VALID:
                print(f"Trip {trip_id} already assigned to route {trip.route_id}")
                return True

            # stale/orphaned/mismatched assignment — repair it first so the
            # existing assignment pipeline receives a genuinely unassigned trip
            if repair_trip_assignment(db, trip):
                db.commit()
                print(f"Trip {trip_id}: repaired invalid assignment state ({status.value})")
                # The commit above ended the transaction — and with it the
                # xact-scoped writer funnel lock. Re-acquire before the
                # mutation phase below, otherwise greedy insertion races the
                # LNS destroy/repair on route_stops rows -> deadlock
                # (observed: UPDATE sequence vs DELETE route_stops).
                if not acquire_writer_lock(db, lock_timeout_s=75):
                    print(f"Trip {trip_id}: writer lock busy after repair, deferring job")
                    return False  # retry the job later

        # Run greedy insertion
        result = greedy_insertion.assign_trip(db, trip)

        if result.success and result.insertion_option:
            # Defensive re-acquire: greedy probing can commit internally
            # (e.g. repair helpers), and any commit releases the funnel.
            # This call is free if we already hold the lock in this txn.
            if not acquire_writer_lock(db):
                print(f"Trip {trip_id}: writer lock busy before insertion, deferring job")
                return False
            # Apply the insertion
            route = greedy_insertion.apply_insertion(db, result.insertion_option, trip)

            # Log audit
            audit_logger.log_greedy_assignment(
                db=db,
                trip=trip,
                route=route,
                insertion_position=result.insertion_option.pickup_sequence,
                cost=result.insertion_option.cost_result.cost,
                distance_delta=result.insertion_option.cost_result.components.extra_distance_km,
                duration_delta=result.insertion_option.cost_result.components.extra_duration_minutes,
                delay_delta=result.insertion_option.cost_result.components.delay_impact_minutes,
                algorithm_version="greedy-v1",
                feasible=True,
            )

            print(f"Assigned trip {trip_id} to route {route.route_id}")
            return True

        elif result.new_route_created:
            # This shouldn't happen - greedy_insertion only returns new_route_created=False
            # New route creation is handled separately
            print(f"Trip {trip_id} needs new route creation")
            return self._create_new_route(db, trip)

        else:
            # No feasible route found - create new route
            print(f"No feasible route for trip {trip_id}, creating new route")
            return self._create_new_route(db, trip)

    def _create_new_route(self, db: Session, trip: Trip) -> bool:
        """Create a new route for a trip when no existing route is feasible."""
        # Find a compatible vehicle
        vehicle = self._find_available_vehicle(db, trip)
        if not vehicle:
            audit_logger.log_assignment_failed(
                db=db,
                trip=trip,
                reason="No available vehicle",
                candidate_count=0,
                feasible_count=0,
            )
            # Mark trip as unassigned
            trip.status = "unassigned"
            db.add(trip)
            db.commit()
            return True  # Don't retry - this is a business decision

        # Find a compatible driver
        driver = self._find_available_driver(db, trip, vehicle)
        if not driver:
            audit_logger.log_assignment_failed(
                db=db,
                trip=trip,
                reason="No available driver",
                candidate_count=0,
                feasible_count=0,
            )
            trip.status = "unassigned"
            db.add(trip)
            db.commit()
            return True

        # Create new route
        route = Route(
            name=f"Route-{trip.trip_id[:8]}",
            driver_id=driver.driver_id,
            vehicle_id=vehicle.vehicle_id,
            pickup_time=trip.pickup_time,
            status="planned",
            version=1,
            frozen_until_sequence=0,
            capacity_kg=vehicle.load_capacity_kg,
            used_capacity_kg=trip.load_weight_kg or 0,
            remaining_capacity_kg=(vehicle.load_capacity_kg or 0) - (trip.load_weight_kg or 0),
        )
        db.add(route)
        db.flush()

        # Create pickup stop
        pickup_stop = RouteStop(
            route_id=route.route_id,
            trip_id=trip.trip_id,
            sequence=1,
            stop_type="pickup",
            address=trip.origin,
            latitude=trip.gps_start_lat,
            longitude=trip.gps_start_lon,
        )
        db.add(pickup_stop)

        # Create delivery stop
        delivery_stop = RouteStop(
            route_id=route.route_id,
            trip_id=trip.trip_id,
            sequence=2,
            stop_type="delivery",
            address=trip.destination,
            latitude=trip.gps_end_lat,
            longitude=trip.gps_end_lon,
        )
        db.add(delivery_stop)

        # Update trip
        trip.route_id = str(route.route_id)
        trip.assigned_at = datetime.now(timezone.utc)
        trip.driver_id = driver.driver_id
        trip.vehicle_id = vehicle.vehicle_id
        if vehicle.vehicle_type:
            trip.vehicle_type = vehicle.vehicle_type
        db.add(trip)

        db.commit()
        db.refresh(route)

        # Log audit
        audit_logger.log_new_route_created(
            db=db,
            trip=trip,
            route=route,
            vehicle_id=vehicle.vehicle_id,
            driver_id=driver.driver_id,
            algorithm_version="greedy-v1",
        )

        print(f"Created new route {route.route_id} for trip {trip.trip_id}")
        return True

    def _find_available_vehicle(self, db: Session, trip: Trip) -> Optional[Vehicle]:
        """Pick the LEAST-LOADED available vehicle that can fit this trip.

        Distribution rules:
        - Only active (or NULL-status, legacy) vehicles of the matching type.
        - A vehicle is only eligible if current fleet load + this trip's load
          never exceeds its capacity.
        - Among eligible vehicles we pick the one with the most free capacity
          (headroom), so new routes spread across the whole fleet instead of
          piling onto the first row (previously ``.first()``).
        """
        query = db.query(Vehicle).filter(
            or_(Vehicle.status == "active", Vehicle.status.is_(None)),
        )

        if trip.vehicle_type:
            query = query.filter(Vehicle.vehicle_type == trip.vehicle_type)
        if trip.load_weight_kg:
            query = query.filter(Vehicle.load_capacity_kg >= trip.load_weight_kg)

        candidates = query.all()
        if not candidates:
            return None

        # Sum of used capacity across each candidate's active routes -- derived
        # from authoritative RouteStop/Trip rows (never from the cached
        # used_capacity_kg columns, which can drift stale).
        scored = []
        for v in candidates:
            used = vehicle_active_load_kg(db, v)
            cap = v.load_capacity_kg or 0
            trip_load = trip.load_weight_kg or  0
            if cap > 0 and used + trip_load > cap:
                continue  # would exceed vehicle aggregate capacity -- not eligible
            scored.append((cap - used, v))  # headroom (higher = better)

        if not scored:
            return None
        # Most headroom first; deterministic tie-break by vehicle_id.
        scored.sort(key=lambda hv: (-hv[0], hv[1].vehicle_id))
        return scored[0][1]

    # Maximum driver hours-of-service per day (shared with the feasibility
    # engine's HOS constraint so both paths enforce the same limit).
    MAX_DRIVER_HOS_HOURS = MAX_DRIVER_HOS_HOURS
    AVG_ROUTE_SPEED_KPH = AVG_ROUTE_SPEED_KPH  # kept for backward compat
    SERVICE_HOURS_PER_STOP = SERVICE_HOURS_PER_STOP

    def _haversine_km(self, lat1, lon1, lat2, lon2) -> float:
        from math import radians, sin, cos, sqrt, atan2

        R = 6371.0
        lat1, lon1, lat2, lon2 = radians(lat1), radians(lon1), radians(lat2), radians(lon2)
        dlat, dlon = lat2 - lat1, lon2 - lon1
        a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
        return 2 * R * atan2(sqrt(a), sqrt(1 - a))

    def _estimate_trip_hours(self, trip: Trip) -> float:
        """Estimated driving hours for a single trip (start -> end).

        Delegates to the shared estimator in the state layer so the new-route
        path and the feasibility engine's HOS check use identical numbers.
        """
        return estimate_trip_hours(trip)

    def _estimate_route_hours(self, route: Route) -> float:
        """Estimated total service hours for a route (travel + per-stop).

        Delegates to the shared estimator in the state layer so the new-route
        path and the feasibility engine's HOS check use identical numbers.
        """
        return estimate_route_hours(route.stops)

    def _driver_worked_hours(self, db: Session, driver_id: str) -> float:
        """Estimated hours assigned to a driver's routes within the current
        rolling duty window (older routes don't count against the 14h clock -
        see state.DUTY_WINDOW_HOURS)."""
        # autoflush=False would hide same-session insertions (see state.py).
        if db.new or db.dirty:
            db.flush()
        routes = db.query(Route).filter(
            Route.driver_id == driver_id,
            Route.status.in_(["planned", "active", "in-transit"]),
            Route.created_at >= duty_window_start(),
        ).all()
        return sum(self._estimate_route_hours(r) for r in routes)

    def _find_available_driver(self, db: Session, trip: Trip, vehicle: Vehicle) -> Optional["Driver"]:
        """Pick the least-loaded available driver, respecting 14h hours-of-service.

        A driver is only eligible if their already-assigned workload PLUS the
        estimated hours of the new route stays within 14 hours/day. Among
        eligible drivers we pick the one with the most free hours so work
        spreads across the team instead of always going to the first row.
        """
        from app.models.driver import Driver

        query = db.query(Driver).filter(
            or_(Driver.status == "active", Driver.status.is_(None)),
        )

        license_type = getattr(trip, "license_type", None)
        if license_type:
            query = query.filter(Driver.license_type == license_type)

        candidates = query.all()
        if not candidates:
            return None

        est_route_hours = self._estimate_trip_hours(trip)
        within_limit = []
        over_limit = []
        for d in candidates:
            worked = self._driver_worked_hours(db, d.driver_id)
            if worked + est_route_hours > self.MAX_DRIVER_HOS_HOURS:
                over_limit.append((worked, d))
            else:
                within_limit.append((worked, d))

        # Prefer drivers within their HOS limit (least-loaded first)
        if within_limit:
            within_limit.sort(key=lambda wd: (wd[0], wd[1].driver_id))
            return within_limit[0][1]

        # All drivers over limit -- pick the least-loaded one so trips still get assigned
        over_limit.sort(key=lambda wd: (wd[0], wd[1].driver_id))
        return over_limit[0][1]


def create_trip_assignment_job(trip_id: str) -> str:
    """Create a trip assignment job in the queue."""
    queue = get_queue()
    return queue.enqueue("trip-assignment", {"trip_id": trip_id})


def sweep_unassigned_trips(batch: int = 25) -> int:
    """Re-enqueue trips that still need assignment.



    A trip enters the sweeper when it is ANY of:


    - genuinely unassigned (``route_id IS NULL``)
    - ``route_id`` points to a non-existent route (orphaned>
    - the referenced route exists but no RouteStop exists for the trip
    -the trip's RouteStop's ``route_id`` does not match ``trip.route_id``


    All of these are repaired by ``_assign_trip``'s state validation before the
    existing assignment pipeline runs; this sweeper just makes sure such trips
    actually get re-enqueued (the old ``route_id IS NULL``-only filter missed
    orphaned trips forever)..
    """

    db = SessionLocal()
    try:
        trips = (
            db.query(Trip)
            .filter(Trip.status.in_(["scheduled", "unassigned"]))
            .order_by(Trip.pickup_time.asc().nullslast())
            .limit(batch * 4)
            .all()
        )
        if not trips:
            return 0



        # Preload route existence (string keys match Trip.route_id's format) and
        # RouteStop route affiliations for the batch to avoid per-trip queries..
        route_ids = {t.route_id for t in trips if t.route_id}
        routes = {
            str(r): True
            for (r,)in db.query(Route.route_id).filter(Route.route_id.in_(route_ids)).all()
        } if route_ids else {}



        stop_rows = (
            db.query(RouteStop.trip_id, RouteStop.route_id)
            .filter(RouteStop.trip_id.in_({t.trip_id for t in trips}))
            .all()
        ) if trips else []
        stops_by_trip = {}
        for trip_id_, route_id_ in stop_rows:

            stops_by_trip.setdefault(trip_id_, set()).add(str(route_id_))



        candidates = []
        for t in trips:
            if not t.route_id:
                candidates.append(t)
                continue
            if str(t.route_id) not in routes:
                candidates.append(t)  # orphaned - route gone
                continue
            matched = stops_by_trip.get(t.trip_id, set())
            if not matched:
                candidates.append(t)  # route exists but no RouteStop
                continue
            if str(t.route_id) not in matched:
                candidates.append(t)  # RouteStop.route_id != Trip.route_id
                continue



        queued = 0
        for t in candidates[:batch]:
            create_trip_assignment_job(t.trip_id)
            queued += 1
        if queued:
            print(f"[SWEEP] re-enqueued {queued} trip(s) needing assignment")
        return queued
    finally:
        db.close()


# Worker instance for running
trip_assignment_worker = TripAssignmentWorker()