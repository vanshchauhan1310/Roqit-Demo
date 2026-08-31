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
from app.infrastructure.queue import Queue, QueueJob, get_queue


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

        # Check if already assigned
        if trip.route_id:
            print(f"Trip {trip_id} already assigned to route {trip.route_id}")
            return True

        # Run greedy insertion
        result = greedy_insertion.assign_trip(db, trip)

        if result.success and result.insertion_option:
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

        # Sum of used capacity across each candidate's active routes.
        route_loads = dict(
            db.query(Route.vehicle_id, func.coalesce(func.sum(Route.used_capacity_kg), 0.0))
            .filter(
                Route.vehicle_id.in_([v.vehicle_id for v in candidates]),
                Route.status.in_(["planned", "active", "in-transit"]),
            )
            .group_by(Route.vehicle_id)
            .all()
        )

        scored = []
        for v in candidates:
            used = float(route_loads.get(v.vehicle_id, 0) or 0)
            cap = v.load_capacity_kg or 0
            trip_load = trip.load_weight_kg or 0
            if cap > 0 and used + trip_load > cap:
                continue  # would exceed vehicle capacity — not eligible
            scored.append((cap - used, v))  # headroom (higher = better)

        if not scored:
            return None
        # Most headroom first; deterministic tie-break by vehicle_id.
        scored.sort(key=lambda hv: (-hv[0], hv[1].vehicle_id))
        return scored[0][1]

    # Maximum driver hours-of-service per day (logistics industry standard).
    MAX_DRIVER_HOS_HOURS = 14.0
    AVG_ROUTE_SPEED_KPH = 40.0
    SERVICE_HOURS_PER_STOP = 0.1  # 6 minutes per stop for pickup/delivery

    def _haversine_km(self, lat1, lon1, lat2, lon2) -> float:
        from math import radians, sin, cos, sqrt, atan2

        R = 6371.0
        lat1, lon1, lat2, lon2 = radians(lat1), radians(lon1), radians(lat2), radians(lon2)
        dlat, dlon = lat2 - lat1, lon2 - lon1
        a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
        return 2 * R * atan2(sqrt(a), sqrt(1 - a))

    def _estimate_trip_hours(self, trip: Trip) -> float:
        """Estimated driving hours for a single trip (start -> end)."""
        if trip.gps_start_lat and trip.gps_start_lon and trip.gps_end_lat and trip.gps_end_lon:
            km = self._haversine_km(
                trip.gps_start_lat, trip.gps_start_lon,
                trip.gps_end_lat, trip.gps_end_lon,
            )
            return (km / self.AVG_ROUTE_SPEED_KPH) + 2 * self.SERVICE_HOURS_PER_STOP
        return self.SERVICE_HOURS_PER_STOP * 2

    def _estimate_route_hours(self, route: Route) -> float:
        """Estimated total service hours for a route (travel + per-stop)."""
        geocoded = [s for s in route.stops if s.latitude and s.longitude]
        total_km = 0.0
        for prev, stop in zip(geocoded, geocoded[1:]):
            total_km += self._haversine_km(prev.latitude, prev.longitude, stop.latitude, stop.longitude)
        return (total_km / self.AVG_ROUTE_SPEED_KPH) + len(route.stops) * self.SERVICE_HOURS_PER_STOP

    def _driver_worked_hours(self, db: Session, driver_id: str) -> float:
        """Total estimated hours already assigned to a driver's active routes."""
        routes = db.query(Route).filter(
            Route.driver_id == driver_id,
            Route.status.in_(["planned", "active", "in-transit"]),
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
        scored = []
        for d in candidates:
            worked = self._driver_worked_hours(db, d.driver_id)
            if worked + est_route_hours > self.MAX_DRIVER_HOS_HOURS:
                continue  # would exceed the 14h service limit
            scored.append((worked, d))  # less-worked first

        if not scored:
            return None
        scored.sort(key=lambda wd: (wd[0], wd[1].driver_id))
        return scored[0][1]


def create_trip_assignment_job(trip_id: str) -> str:
    """Create a trip assignment job in the queue."""
    queue = get_queue()
    return queue.enqueue("trip-assignment", {"trip_id": trip_id})


def sweep_unassigned_trips(batch: int = 25) -> int:
    """Re-enqueue trips that are still unassigned (route_id IS NULL).

    The auto-feed / external source can create trips while the worker is
    briefly down or when a job is lost; this sweeper drains that backlog so
    the Live Ops "queue depth" returns to ~0 when the feed is idle.
    """
    db = SessionLocal()
    try:
        trips = (
            db.query(Trip)
            .filter(Trip.route_id.is_(None))
            .order_by(Trip.pickup_time.asc().nullslast())
            .limit(batch)
            .all()
        )
        queued = 0
        for t in trips:
            if t.status not in ("scheduled", "unassigned"):
                continue
            create_trip_assignment_job(t.trip_id)
            queued += 1
        if queued:
            print(f"[SWEEP] re-enqueued {queued} unassigned trip(s) for assignment")
        return queued
    finally:
        db.close()


# Worker instance for running
trip_assignment_worker = TripAssignmentWorker()