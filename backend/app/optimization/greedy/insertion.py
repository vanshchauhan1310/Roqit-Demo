"""Greedy Best Insertion algorithm for real-time trip assignment."""

from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.route import Route, RouteStop
from app.models.trip import Trip
from app.models.vehicle import Vehicle
from app.models.driver import Driver
from app.optimization.feasibility.engine import FeasibilityEngine, FeasibilityResult
from app.optimization.scoring.cost_function import CostFunction, InsertionCostResult
from app.optimization.candidates.search import CandidateSearch, CandidateRoute


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
    """Greedy Best Insertion for online trip assignment."""

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
        6. If no feasible route, return failure (caller creates new route)
        """
        # Step 1: Find candidate routes
        candidates = self.candidate_search.find_candidates(db, trip)

        if not candidates:
            return GreedyResult(
                success=False,
                error_message="No candidate routes found",
            )

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

        return GreedyResult(
            success=False,
            error_message="No feasible insertion found in any candidate route",
        )

    def _find_best_insertion_for_route(
        self,
        db: Session,
        candidate: CandidateRoute,
        trip: Trip,
    ) -> Optional[InsertionOption]:
        """Find the best feasible insertion position for a trip in a specific route."""
        route = candidate.route
        vehicle = candidate.vehicle

        if not vehicle:
            return None

        # Get current stops ordered by sequence
        current_stops = sorted(route.stops, key=lambda s: s.sequence)

        # Find frozen boundary
        frozen_until = route.frozen_until_sequence or 0

        # Valid insertion positions for pickup: after frozen stops, before any delivery
        # For a new trip, pickup must come before delivery
        # We try all valid (pickup_seq, delivery_seq) pairs

        best_option: Optional[InsertionOption] = None
        best_cost = float('inf')

        # Determine valid sequence range for insertion
        # Pickup can be inserted at any position >= frozen_until + 1
        # Delivery must be after pickup
        min_pickup_seq = frozen_until + 1
        max_seq = len(current_stops) + 1  # Can append at end

        for pickup_seq in range(min_pickup_seq, max_seq + 1):
            for delivery_seq in range(pickup_seq + 1, max_seq + 2):
                # Create new stops list with insertion
                new_stops = self._insert_stops_at_position(
                    current_stops, trip, pickup_seq, delivery_seq
                )

                # Check feasibility
                feasibility = self.feasibility_engine.check_route_feasibility(
                    db, route, new_stops, trip, vehicle,
                    db.get(Driver, route.driver_id) if route.driver_id else None
                )

                if not feasibility.feasible:
                    continue

                # Calculate cost
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
        """Create new stops list with trip pickup/delivery inserted at given positions."""
        # This creates a new list with the stops inserted
        # The actual sequence numbers will be reassigned after insertion
        new_stops = []

        pickup_stop = RouteStop(
            trip_id=trip.trip_id,
            stop_type="pickup",
            address=trip.origin,
            latitude=trip.gps_start_lat,
            longitude=trip.gps_start_lon,
            sequence=pickup_seq,
        )

        delivery_stop = RouteStop(
            trip_id=trip.trip_id,
            stop_type="delivery",
            address=trip.destination,
            latitude=trip.gps_end_lat,
            longitude=trip.gps_end_lon,
            sequence=delivery_seq,
        )

        # Insert stops at correct positions
        pickup_inserted = False
        delivery_inserted = False

        for i, stop in enumerate(current_stops):
            # Check if we need to insert pickup before this stop
            if not pickup_inserted and i + 1 >= pickup_seq:
                new_stops.append(pickup_stop)
                pickup_inserted = True

            # Check if we need to insert delivery before this stop
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
        db.add(trip)

        db.commit()
        db.refresh(route)

        return route


# Global instance
greedy_insertion = GreedyInsertion()