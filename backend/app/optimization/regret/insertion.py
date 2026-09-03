"""Regret Insertion algorithms for LNS repair.

Regret-k insertion prioritizes trips where the difference between
best and k-th best insertion cost is highest.
"""

import time
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
from app.optimization.state import _haversine_km, vehicle_active_load_kg
from app.optimization.state import ACTIVE_STATUSES, _haversine_km, vehicle_active_load_kg

class RepairTimeout(Exception):
    """Raised when the LNS repair phase exceeds its wall-clock deadline.

    The optimizer treats this as a benign "iteration rejected" signal: the
    caller rolls the iteration back and stops the search, releasing the
    writer funnel lock promptly instead of burning minutes of CPU (and
    starving the trip-assignment / completion workers) inside one slow
    regret-k insertion pass.
    """


# Cooperative deadline for the CURRENT repair phase (module-level because
# the repair operators are shared singleton instances). Only one LNS run
# executes at a time (guarded by the writer funnel lock), so a single
# slot is safe.
_repair_deadline: Optional[float] = None


def set_repair_deadline(seconds: Optional[float]) -> None:
    """Arm (seconds=float) or disarm (None) the repair deadline."""
    global _repair_deadline
    _repair_deadline = (time.monotonic() + seconds) if seconds is not None else None


def _check_repair_deadline() -> None:
    if _repair_deadline is not None and time.monotonic() > _repair_deadline:
        raise RepairTimeout("LNS repair exceeded its wall-clock deadline")


# Public alias for repair operators (greedy repair) to share the deadline.
check_repair_deadline = _check_repair_deadline


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

        # Prune the route candidate set up-front: completed / inactive routes
        # never accept new stops (their driver HOS window has closed), and very
        # large routes blow up the O(stops^2) regret sweep. At demo scale this
        # cuts the candidate set from ~21 routes to ~11, shaving tens of seconds
        # off the repair pass so the wall-clock deadline is no longer hit.
        candidate_routes: list[Route] = [
            r
            for r in routes
            if r.status is not None and r.status.lower() in ACTIVE_STATUSES
            and len(r.stops or []) <= 30
        ]
        if not candidate_routes:
            candidate_routes = routes

        for trip in trips:
            try:
                _check_repair_deadline()
            except RepairTimeout:
                # Deadline expired between trips — stop re-scanning but keep
                # the partial results so the optimizer can still evaluate.
                break
            result = self._find_all_insertions(db, trip, candidate_routes)
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

            try:
                # Find best insertions for this route
                options = self._find_route_insertions(db, route, vehicle, trip)
            except RepairTimeout:
                # Deadline expired mid-sweep — return whatever was found so far.
                # The optimizer can still evaluate a partial candidate instead of
                # discarding the entire repair (which caused it to abort after
                # exactly 1 iteration every run).
                break
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
        """Find all feasible insertions for a trip in a specific route.

        The position sweep below is O(stops^2) with a full feasibility
        simulation per pair, so large routes dominate the repair cost. Two
        cheap pre-filters keep the sweep off routes that cannot help:

        - capacity: skip when the vehicle's remaining capacity cannot take
          the trip's load at all (every pair would be infeasible anyway);
        - distance: skip when the route's nearest stop is unrealistically
          far from the trip origin (detour cost alone makes any insertion
          the worst candidate; regret-k still has the other routes).

        At demo scale (16 routes, ~40 stops each) these prunes cut the
        repair phase from minutes to well inside its wall-clock deadline.
        """
        current_stops = sorted(route.stops, key=lambda s: s.sequence)
        frozen_until = route.frozen_until_sequence or 0

        # --- Pre-filter 1: vehicle capacity ---------------------------------
        load = vehicle_active_load_kg(db, vehicle)
        cap = vehicle.load_capacity_kg or 0.0
        trip_load = trip.load_weight_kg or 0.0
        if cap > 0 and (load + trip_load) > cap:
            return []

        # --- Pre-filter 2: distance sanity -----------------------------------
        # Skip routes whose every stop is farther than PRUNE_DISTANCE_KM from
        # the trip origin — inserting there can never be cost-competitive.
        PRUNE_DISTANCE_KM = 150.0
        if trip.gps_start_lat and trip.gps_start_lon:
            near_enough = any(
                s.latitude and s.longitude
                and _haversine_km(trip.gps_start_lat, trip.gps_start_lon, s.latitude, s.longitude)
                <= PRUNE_DISTANCE_KM
                for s in current_stops
            )
            if not near_enough:
                return []

        # Driver is constant for the whole route — hoist the lookup out of
        # the O(n^2) loop (it used to run once per position pair).
        driver = db.get(Driver, route.driver_id) if route.driver_id else None

        options: list[InsertionOption] = []

        min_pickup_seq = frozen_until + 1
        max_seq = len(current_stops) + 1

        for pickup_seq in range(min_pickup_seq, max_seq + 1):
            _check_repair_deadline()
            for delivery_seq in range(pickup_seq + 1, max_seq + 2):
                new_stops = self.greedy_insertion._insert_stops_at_position(
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
