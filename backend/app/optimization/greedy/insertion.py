"""Greedy Best Insertion algorithm for real-time trip assignment.

When no feasible route exists, automatically creates a new route with an
available driver and vehicle so the trip assignment never fails due to
capacity constraints.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import and_, not_, func
from sqlalchemy.orm import Session

from app.models.route import Route, RouteStop
from app.models.trip import Trip
from app.models.vehicle import Vehicle
from app.models.driver import Driver
from app.optimization.feasibility.engine import FeasibilityEngine, FeasibilityResult
from app.optimization.scoring.cost_function import CostFunction, InsertionCostResult
from app.optimization.candidates.search import CandidateSearch, CandidateRoute
from app.optimization.state import acquire_writer_lock, sync_route_capacity


@dataclass
class InsertionOption:
    """A feasible insertion option for a trip into a route."""
    route: Route
    vehicle: Vehicle
    pickup_sequence: int
    delivery_sequence: int
    cost_result: InsertionCostResult
    feasibility: FeasibilityResult


@dataclass
class GreedyResult:
    """Result of greedy insertion."""
    success: bool
    route: Optional[Route] = None
    vehicle: Optional[Vehicle] = None
    insertion_option: Optional[InsertionOption] = None
    new_route_created: bool = False
    error_message: Optional[str] = None


class GreedyInsertion:
    """Greedy Best Insertion for online trip assignment.

    When all existing routes are full (capacity exceeded), automatically
    creates a new route with an available driver and vehicle.
    """

    def __init__(
        self,
        feasibility_engine: Optional[FeasibilityEngine] = None,
        cost_function: Optional[CostFunction] = None,
        candidate_search: Optional[CandidateSearch] = None,
    ):
        self.feasibility_engine = feasibility_engine or FeasibilityEngine()
        self.cost_function = cost_function or CostFunction()
        self.candidate_search = candidate_search or CandidateSearch()

    def assign_trip(
        self,
        db: Session,
        trip: Trip,
    ) -> GreedyResult:
        """Assign a trip to the best feasible route using greedy best insertion.

        Flow:
        1. Find candidate routes
        2. For each candidate, try all valid insertion positions
        3. Check feasibility for each position
        4. Calculate cost for feasible positions
        5. Select minimum cost feasible insertion
        6. If no feasible route, create new route with available driver/vehicle
        """
        # Step 1: Find candidate routes
        candidates = self.candidate_search.find_candidates(db, trip)

        # Step 2-5: Try all valid insertions for each candidate
        best_option: Optional[InsertionOption] = None
        best_cost = float('inf')

        for candidate in candidates:
            option = self._find_best_insertion_for_route(db, candidate, trip)
            if option and option.cost_result.cost < best_cost:
                best_cost = option.cost_result.cost
                best_option = option

        if best_option:
            return GreedyResult(
                success=True,
                route=best_option.route,
                vehicle=best_option.vehicle,
                insertion_option=best_option,
                new_route_created=False,
            )

        # Step 6: No feasible insertion found - create new route with available driver/vehicle
        print(f"[GreedyInsertion] No feasible route for trip {trip.trip_id}, creating new route with available driver/vehicle")
        new_route_result = self._create_new_route_with_driver_vehicle(db, trip)
        return new_route_result

    def _create_new_route_with_driver_vehicle(
        self,
        db: Session,
        trip: Trip,
    ) -> GreedyResult:
        """Create a new route with an available driver and vehicle.

        Finds drivers and vehicles that are not currently assigned to any
        active route, creates a new route, and assigns the trip to it.
        """
        try:
            # Find available drivers (not assigned to any active route)
            active_route_driver_ids = [
                r.driver_id for r in db.query(Route.driver_id).filter(
                    Route.status.in_(["planned", "active", "in-transit"]),
                    Route.driver_id.isnot(None)
                ).all()
            ]

            available_drivers = db.query(Driver).filter(
                Driver.status == "available",
                not_(Driver.driver_id.in_(active_route_driver_ids)) if active_route_driver_ids else True
            ).order_by(Driver.rating.desc()).all()

            # Find available vehicles (not assigned to any active route)
            active_route_vehicle_ids = [
                r.vehicle_id for r in db.query(Route.vehicle_id).filter(
                    Route.status.in_(["planned", "active", "in-transit"]),
                    Route.vehicle_id.isnot(None)
                ).all()
            ]
            available_vehicles = db.query(Vehicle).filter(
                Vehicle.status == "available",
                not_(Vehicle.vehicle_id.in_(active_route_vehicle_ids)) if active_route_vehicle_ids else True
            ).order_by(Vehicle.load_capacity_kg.desc()).all()

            # Filter vehicles by capacity requirement
            trip_load = trip.load_weight_kg or 0
            suitable_vehicles = [v for v in available_vehicles if (v.load_capacity_kg or 0) >= trip_load]

            if not available_drivers:
                return GreedyResult(
                    success=False,
                    error_message="No available drivers found",
                )

            if not suitable_vehicles:
                return GreedyResult(
                    success=False,
                    error_message=f"No available vehicle with sufficient capacity (need {trip_load}kg)",
                )

            # Select best driver (highest rated) and best vehicle (smallest sufficient capacity)
            selected_driver = available_drivers[0]
            selected_vehicle = suitable_vehicles[0]  # Already sorted by capacity desc, but we want smallest sufficient
            suitable_vehicles.sort(key=lambda v: v.load_capacity_kg or 0)
            selected_vehicle = suitable_vehicles[0]

            # Create new route
            new_route = Route(
                route_id=uuid.uuid4(),
                name=f"Route-{trip.trip_id[:8]}",
                status="planned",
                driver_id=selected_driver.driver_id,
                vehicle_id=selected_vehicle.vehicle_id,
                capacity_kg=selected_vehicle.load_capacity_kg,
                used_capacity_kg=0,
                remaining_capacity_kg=selected_vehicle.load_capacity_kg,
            )
            db.add(new_route)
            db.flush()  # Get the route_id

            # Create pickup and delivery stops for the trip
            pickup_stop = RouteStop(
                route_id=new_route.route_id,
                trip_id=trip.trip_id,
                sequence=1,
                stop_type="pickup",
                address=trip.origin,
                latitude=trip.gps_start_lat,
                longitude=trip.gps_start_lon,
            )
            delivery_stop = RouteStop(
                route_id=new_route.route_id,
                trip_id=trip.trip_id,
                sequence=2,
                stop_type="delivery",
                address=trip.destination,
                latitude=trip.gps_end_lat,
                longitude=trip.gps_end_lon,
            )
            db.add(pickup_stop)
            db.add(delivery_stop)

            # Update route capacity
            new_route.used_capacity_kg = trip_load
            new_route.remaining_capacity_kg = (selected_vehicle.load_capacity_kg or 0) - trip_load

            # Assign trip to route
            trip.route_id = str(new_route.route_id)
            trip.assigned_at = datetime.now(timezone.utc)
            db.add(trip)

            db.commit()
            db.refresh(new_route)

            print(f"[GreedyInsertion] Created new route {new_route.route_id} with driver {selected_driver.driver_id} and vehicle {selected_vehicle.vehicle_id}")

            return GreedyResult(
                success=True,
                route=new_route,
                vehicle=selected_vehicle,
                new_route_created=True,
            )

        except Exception as e:
            db.rollback()
            return GreedyResult(
                success=False,
                error_message=f"Failed to create new route: {str(e)}",
            )
    def _find_best_insertion_for_route(
        self,
        db: Session,
        candidate: CandidateRoute,
        trip: Trip,
    ) -> Optional[InsertionOption]:
        """Find the best insertion position for a trip in a candidate route."""
        route = candidate.route
        vehicle = candidate.vehicle
        driver = candidate.driver

        if not vehicle:
            return None

        current_stops = sorted(route.stops, key=lambda s: s.sequence)
        frozen_until = route.frozen_until_sequence or 0
        min_pickup_seq = frozen_until + 1
        max_seq = len(current_stops) + 1

        best_option: Optional[InsertionOption] = None
        best_cost = float('inf')

        for pickup_seq in range(min_pickup_seq, max_seq + 1):
            for delivery_seq in range(pickup_seq + 1, max_seq + 2):
                new_stops = self._insert_stops_at_position(
                    current_stops, trip, pickup_seq, delivery_seq
                )

                feasibility = self.feasibility_engine.check_route_feasibility(
                    db, route, new_stops, trip, vehicle, driver
                )

                if not feasibility.feasible:
                    continue

                cost_result = self.cost_function.calculate_insertion_cost(
                    db, route, current_stops, new_stops, trip, vehicle
                )

                if cost_result.cost < best_cost:
                    best_cost = cost_result.cost
                    best_option = InsertionOption(
                        route=route,
                        vehicle=vehicle,
                        pickup_sequence=pickup_seq,
                        delivery_sequence=delivery_seq,
                        cost_result=cost_result,
                        feasibility=feasibility,
                    )

        return best_option

    def _insert_stops_at_position(
        self,
        current_stops: list[RouteStop],
        trip: Trip,
        pickup_seq: int,
        delivery_seq: int,
    ) -> list[RouteStop]:
        """Create a new stop list with pickup and delivery inserted at given positions."""
        from dataclasses import dataclass
        from typing import Optional

        @dataclass
        class TempStop:
            stop_id: Optional[uuid.UUID] = None
            trip_id: Optional[str] = None
            sequence: int = 0
            stop_type: str = "waypoint"
            address: Optional[str] = None
            latitude: Optional[float] = None
            longitude: Optional[float] = None

        pickup_stop = TempStop(
            trip_id=trip.trip_id,
            stop_type="pickup",
            address=trip.origin,
            latitude=trip.gps_start_lat,
            longitude=trip.gps_start_lon,
        )
        delivery_stop = TempStop(
            trip_id=trip.trip_id,
            stop_type="delivery",
            address=trip.destination,
            latitude=trip.gps_end_lat,
            longitude=trip.gps_end_lon,
        )

        # Build temporary stop list with proper sequences
        temp_stops = []
        for s in current_stops:
            temp_stops.append(TempStop(
                stop_id=s.stop_id,
                trip_id=s.trip_id,
                sequence=s.sequence,
                stop_type=s.stop_type,
                address=s.address,
                latitude=s.latitude,
                longitude=s.longitude,
            ))

        # Insert at positions
        new_stops = []
        pickup_inserted = False
        delivery_inserted = False

        for i, stop in enumerate(temp_stops):
            if not pickup_inserted and i + 1 >= pickup_seq:
                new_stops.append(pickup_stop)
                pickup_inserted = True

            if not delivery_inserted and i + 1 >= delivery_seq:
                new_stops.append(delivery_stop)
                delivery_inserted = True

            new_stops.append(stop)

        # Handle append at end
        if not pickup_inserted:
            new_stops.append(pickup_stop)
        if not delivery_inserted:
            new_stops.append(delivery_stop)

        # Renumber sequences
        for idx, stop in enumerate(new_stops):
            stop.sequence = idx + 1

        return new_stops

    def apply_insertion(
        self,
        db: Session,
        insertion_option: InsertionOption,
        trip: Trip,
    ) -> Route:
        """Apply the insertion to the database.

        This performs the actual database modifications:
        1. Create new RouteStop entries for pickup and delivery
        2. Update sequence numbers of affected stops
        3. Update route metrics
        4. Update trip assignment
        """
        route = insertion_option.route
        pickup_seq = insertion_option.pickup_sequence
        delivery_seq = insertion_option.delivery_sequence

        # Get current stops
        current_stops = sorted(route.stops, key=lambda s: s.sequence)

        # Create new stops with insertion
        new_stops = self._insert_stops_at_position(current_stops, trip, pickup_seq, delivery_seq)

        # Update sequences in database
        for stop in new_stops:
            if stop.stop_id:  # Existing stop
                existing = db.get(RouteStop, stop.stop_id)
                if existing:
                    existing.sequence = stop.sequence
                    db.add(existing)
            else:  # New stop (pickup/delivery)
                # Create new RouteStop
                new_route_stop = RouteStop(
                    route_id=route.route_id,
                    trip_id=stop.trip_id,
                    sequence=stop.sequence,
                    stop_type=stop.stop_type,
                    address=stop.address,
                    latitude=stop.latitude,
                    longitude=stop.longitude,
                )
                db.add(new_route_stop)

        # Update route version for optimistic locking
        route.version = (route.version or 0) + 1
        db.add(route)

        # Update trip assignment
        trip.route_id = str(route.route_id)
        trip.assigned_at = datetime.now(timezone.utc)
        db.add(trip)

        db.commit()
        db.refresh(route)

        # The commit above released the xact-scoped writer funnel lock.
        # sync_route_capacity mutates the route row below, so re-acquire the
        # funnel first - otherwise it can deadlock with a concurrent LNS
        # destroy/repair touching the same route.
        if not acquire_writer_lock(db):
            raise TimeoutError("writer funnel lock busy (lock_timeout) before capacity sync")

        # Synchronise cached capacity fields from the authoritative stops so
        # used/remaining capacity never drift stale after an insertion (route
        # mutations must keep cached fields consistent per state rules).
        sync_route_capacity(db, route)
        db.commit()

        return route


# Global instance
greedy_insertion = GreedyInsertion()
