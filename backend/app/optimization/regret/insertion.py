"""Regret Insertion algorithms for LNS repair.

Regret-k insertion prioritizes trips where the difference between
best and k-th best insertion cost is highest.
"""

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
from app.optimization.greedy.insertion import GreedyInsertion, InsertionOption


@dataclass
class RegretInsertionResult:
    """Result of regret insertion for a single trip."""
    trip: Trip
    best_option: Optional[InsertionOption]
    regret_value: float  # Difference between best and k-th best
    all_options: list[InsertionOption]


class RegretInsertion:
    """Regret-k insertion for LNS repair phase."""

    def __init__(
        self,
        k: int = 2,
        feasibility_engine: Optional[FeasibilityEngine] = None,
        cost_function: Optional[CostFunction] = None,
        greedy_insertion: Optional[GreedyInsertion] = None,
    ):
        self.k = k
        self.feasibility_engine = feasibility_engine or FeasibilityEngine()
        self.cost_function = cost_function or CostFunction()
        self.greedy_insertion = greedy_insertion or GreedyInsertion(
            feasibility_engine=self.feasibility_engine,
            cost_function=self.cost_function,
        )

    def repair(
        self,
        db: Session,
        trips: list[Trip],
        routes: list[Route],
    ) -> list[InsertionOption]:
        """Repair a destroyed solution by reinserting trips using regret-k.

        Args:
            db: Database session
            trips: List of trips to reinsert (removed during destroy)
            routes: Current routes (with some trips removed)

        Returns:
            List of insertion options for each trip
        """
        # For each trip, find all feasible insertions across all routes
        trip_results: list[RegretInsertionResult] = []

        for trip in trips:
            result = self._find_all_insertions(db, trip, routes)
            trip_results.append(result)

        # Sort by regret value (descending) - highest regret first
        trip_results.sort(key=lambda r: r.regret_value, reverse=True)

        # Insert trips in regret order
        committed_options = []
        for result in trip_results:
            if result.best_option:
                # Apply insertion to update routes for subsequent trips
                self.greedy_insertion.apply_insertion(db, result.best_option, result.trip)
                committed_options.append(result.best_option)
                # Refresh route state for next iteration
                db.refresh(result.best_option.route)

        return committed_options

    def _find_all_insertions(
        self,
        db: Session,
        trip: Trip,
        routes: list[Route],
    ) -> RegretInsertionResult:
        """Find all feasible insertions for a trip across all routes."""
        all_options: list[InsertionOption] = []

        for route in routes:
            vehicle = db.get(Vehicle, route.vehicle_id) if route.vehicle_id else None
            if not vehicle:
                continue

            # Find best insertions for this route
            options = self._find_route_insertions(db, route, vehicle, trip)
            all_options.extend(options)

        # Sort by cost
        all_options.sort(key=lambda o: o.cost_result.cost)

        # Calculate regret-k value
        regret_value = 0.0
        if len(all_options) >= self.k:
            regret_value = all_options[self.k - 1].cost_result.cost - all_options[0].cost_result.cost
        elif len(all_options) > 1:
            regret_value = all_options[-1].cost_result.cost - all_options[0].cost_result.cost

        best_option = all_options[0] if all_options else None

        return RegretInsertionResult(
            trip=trip,
            best_option=best_option,
            regret_value=regret_value,
            all_options=all_options,
        )

    def _find_route_insertions(
        self,
        db: Session,
        route: Route,
        vehicle: Vehicle,
        trip: Trip,
    ) -> list[InsertionOption]:
        """Find all feasible insertions for a trip in a specific route."""
        current_stops = sorted(route.stops, key=lambda s: s.sequence)
        frozen_until = route.frozen_until_sequence or 0

        options: list[InsertionOption] = []

        min_pickup_seq = frozen_until + 1
        max_seq = len(current_stops) + 1

        for pickup_seq in range(min_pickup_seq, max_seq + 1):
            for delivery_seq in range(pickup_seq + 1, max_seq + 2):
                new_stops = self.greedy_insertion._insert_stops_at_position(
                    current_stops, trip, pickup_seq, delivery_seq
                )

                feasibility = self.feasibility_engine.check_route_feasibility(
                    db, route, new_stops, trip, vehicle,
                    db.get(Driver, route.driver_id) if route.driver_id else None
                )

                if not feasibility.feasible:
                    continue

                cost_result = self.cost_function.calculate_insertion_cost(
                    db, route, current_stops, new_stops, trip, vehicle
                )

                options.append(InsertionOption(
                    route=route,
                    vehicle=vehicle,
                    pickup_sequence=pickup_seq,
                    delivery_sequence=delivery_seq,
                    cost_result=cost_result,
                    feasibility=feasibility,
                ))

        return options


# Instances for different k values
regret_2_insertion = RegretInsertion(k=2)
regret_3_insertion = RegretInsertion(k=3)