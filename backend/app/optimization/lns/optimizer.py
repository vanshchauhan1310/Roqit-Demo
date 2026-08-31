"""LNS Optimizer - coordinates destroy and repair for global improvement."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.route import Route, RouteStop
from app.models.trip import Trip
from app.optimization.lns.destroy import (
    DestroyOperator, DestroyResult,
    random_destroy, worst_cost_destroy, related_destroy,
    route_destroy, delay_destroy
)
from app.optimization.lns.repair import (
    RepairOperator, RepairOperator as RepairOp,
    greedy_repair, regret_2_repair, regret_3_repair
)
from app.optimization.scoring.cost_function import CostFunction
from app.optimization.audit.logger import OptimizationAuditLogger


class LNSDestroyStrategy(Enum):
    RANDOM = "random"
    WORST_COST = "worst_cost"
    RELATED = "related"
    ROUTE = "route"
    DELAY = "delay"


class LNSRepairStrategy(Enum):
    GREEDY = "greedy"
    REGRET_2 = "regret_2"
    REGRET_3 = "regret_3"


@dataclass
class LNSSolution:
    """A candidate solution from LNS."""
    routes: list[Route]
    total_cost: float
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class LNSResult:
    """Result of LNS optimization run."""
    success: bool
    improvement: float = 0.0  # Positive = improvement
    old_cost: float = 0.0
    new_cost: float = 0.0
    routes_affected: int = 0
    trips_reinserted: int = 0
    execution_time_ms: int = 0
    destroy_strategy: str = ""
    repair_strategy: str = ""
    error_message: Optional[str] = None
    # Full per-route plan snapshots for before/after comparison (JSON-safe).
    before_routes: Optional[dict] = None
    after_routes: Optional[dict] = None


class LNSOptimizer:
    """Large Neighborhood Search optimizer for periodic global improvement."""

    def __init__(
        self,
        cost_function: Optional[CostFunction] = None,
        destroy_strategy: LNSDestroyStrategy = LNSDestroyStrategy.RANDOM,
        repair_strategy: LNSRepairStrategy = LNSRepairStrategy.REGRET_2,
        destroy_percentage: float = 0.2,
        acceptance_threshold: float = 0.0,  # Only accept if improvement > threshold
    ):
        self.cost_function = cost_function or CostFunction()
        self.destroy_strategy = destroy_strategy
        self.repair_strategy = repair_strategy
        self.destroy_percentage = destroy_percentage
        self.acceptance_threshold = acceptance_threshold

        # Map strategies to operators
        self.destroy_operators = {
            LNSDestroyStrategy.RANDOM: random_destroy,
            LNSDestroyStrategy.WORST_COST: worst_cost_destroy,
            LNSDestroyStrategy.RELATED: related_destroy,
            LNSDestroyStrategy.ROUTE: route_destroy,
            LNSDestroyStrategy.DELAY: delay_destroy,
        }

        self.repair_operators = {
            LNSRepairStrategy.GREEDY: greedy_repair,
            LNSRepairStrategy.REGRET_2: regret_2_repair,
            LNSRepairStrategy.REGRET_3: regret_3_repair,
        }

        self.audit_logger = OptimizationAuditLogger()

    def optimize(
        self,
        db: Session,
        routes: list[Route],
        run_id: Optional[UUID] = None,
    ) -> LNSResult:
        """Run multi-iteration LNS optimization on selected routes.

        A real LNS search loop, not a single dice-roll:
        1. Snapshot the plan and compute the baseline cost
        2. Loop (until time budget / max iterations):
             destroy (randomized size) -> repair -> evaluate
             - candidate better -> commit it and keep searching from it
             - candidate worse  -> roll back and try a different destroy
        3. The live plan is monotonically never worse than the baseline;
           every accepted iteration compounds.
        """
        import time
        import random as _random

        from app.core.config import settings

        start_time = time.time()
        budget_s = settings.LNS_ITERATION_BUDGET_SECONDS
        max_iterations = settings.LNS_MAX_ITERATIONS
        threshold = self.acceptance_threshold

        destroy_op = self.destroy_operators[self.destroy_strategy]
        repair_op = self.repair_operators[self.repair_strategy]

        # Baseline
        before_plan = self._serialize_plan(db, routes)
        old_cost = self._calculate_total_cost(db, routes)
        current_cost = old_cost

        total_improvement = 0.0
        total_reinserted = 0
        modified_route_ids: set = set()
        iterations = 0
        accepted_iterations = 0
        saw_removable = False
        error_message: Optional[str] = None

        print(f"[LNS] search start: baseline={old_cost:.2f} "
              f"budget={budget_s}s max_iter={max_iterations}")

        while iterations < max_iterations and (time.time() - start_time) < budget_s:
            iterations += 1
            # State to restore if THIS iteration is rejected.
            iter_state = self._capture_route_state(db, routes)
            try:
                # Randomize destroy size around the configured percentage —
                # diversity between iterations is what makes LNS work.
                pct = min(0.5, max(0.1, self.destroy_percentage * _random.uniform(0.7, 1.4)))
                destroy_result = destroy_op.destroy(db, routes, pct)

                if not destroy_result.removed_trips:
                    db.rollback()
                    print(f"[LNS] iter {iterations}: nothing to remove, skipping")
                    continue

                saw_removable = True

                # REPAIR phase
                repair_options = repair_op.repair(db, destroy_result, routes)

                # Evaluate the candidate plan
                new_cost = self._calculate_total_cost(db, routes)
                improvement = current_cost - new_cost

                if improvement > threshold:
                    # ACCEPT: repair already committed; keep searching from here.
                    db.commit()
                    current_cost = new_cost
                    total_improvement += improvement
                    total_reinserted += len(repair_options)
                    modified_route_ids.update(r.route_id for r in destroy_result.modified_routes)
                    accepted_iterations += 1
                    print(f"[LNS] iter {iterations}: ACCEPTED +{improvement:.2f} -> cost={current_cost:.2f}")
                else:
                    # REJECT: candidate worse — restore pre-iteration state.
                    self._rollback_to_state(db, iter_state)
                    db.commit()
                    print(f"[LNS] iter {iterations}: rejected (worse by {abs(improvement):.2f}), rolled back")

            except Exception as e:
                # Unexpected error in this iteration: restore and abort safely.
                self._rollback_to_state(db, iter_state)
                db.commit()
                error_message = f"iteration {iterations}: {e}"
                print(f"[LNS] iter {iterations}: ERROR, rolled back and aborted: {e}")
                break

        execution_time = int((time.time() - start_time) * 1000)
        after_plan = self._serialize_plan(db, routes)
        improvement_total = old_cost - current_cost
        accepted = accepted_iterations > 0 and improvement_total > threshold

        if not saw_removable and error_message is None:
            error_message = "No trips to remove"
        elif not accepted and error_message is None and saw_removable:
            error_message = f"No improvement found in {iterations} iteration(s)"

        # Persist the aggregate run: baseline vs final plan.
        self.audit_logger.log_lns_run(
            db=db,
            run_id=run_id,
            old_cost=old_cost,
            new_cost=current_cost,
            improvement=improvement_total,
            routes_affected=len(modified_route_ids),
            trips_reinserted=total_reinserted,
            execution_time_ms=execution_time,
            destroy_strategy=self.destroy_strategy.value,
            repair_strategy=self.repair_strategy.value,
            accepted=accepted,
            routes_before=before_plan,
            routes_after=after_plan,
        )

        print(f"[LNS] search done: iterations={iterations} accepted={accepted_iterations} "
              f"cost {old_cost:.2f} -> {current_cost:.2f} ({improvement_total:+.2f}) in {execution_time}ms")

        return LNSResult(
            success=accepted,
            improvement=improvement_total,
            old_cost=old_cost,
            new_cost=current_cost,
            routes_affected=len(modified_route_ids),
            trips_reinserted=total_reinserted,
            execution_time_ms=execution_time,
            destroy_strategy=self.destroy_strategy.value,
            repair_strategy=self.repair_strategy.value,
            error_message=error_message if not accepted else None,
            before_routes=before_plan,
            after_routes=after_plan,
        )

    def _calculate_total_cost(self, db: Session, routes: list[Route]) -> float:
        """Calculate total cost of all routes."""
        total = 0.0
        for route in routes:
            stops = sorted(route.stops, key=lambda s: s.sequence)
            vehicle = db.get(type(route.vehicle), route.vehicle_id) if route.vehicle_id else None
            if vehicle and len(stops) >= 2:
                # Use cost function to evaluate route
                # For simplicity, use distance + duration
                total += self._route_cost(db, route, stops, vehicle)
        return total

    def _route_cost(self, db: Session, route: Route, stops: list, vehicle) -> float:
        """Calculate cost of a single route (network-free haversine estimates)."""
        from math import radians, sin, cos, sqrt, atan2
        R = 6371.0
        AVG_SPEED_KPH = 40.0

        total_distance = 0.0
        total_duration = 0.0

        geocoded = [s for s in stops if s.latitude and s.longitude]
        for prev, stop in zip(geocoded, geocoded[1:]):
            # Haversine distance
            lat1, lon1 = radians(prev.latitude), radians(prev.longitude)
            lat2, lon2 = radians(stop.latitude), radians(stop.longitude)
            dlat = lat2 - lat1
            dlon = lon2 - lon1
            a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
            c = 2 * atan2(sqrt(a), sqrt(1-a))
            dist_km = R * c
            total_distance += dist_km
            total_duration += (dist_km / AVG_SPEED_KPH) * 3600

        # Weighted cost
        return total_distance * 0.3 + (total_duration / 60) * 0.25

    def _capture_route_state(self, db: Session, routes: list[Route]) -> dict:
        """Capture current route state for rollback (verses, stops, trip routes)."""
        state = {}
        route_ids = [r.route_id for r in routes if r is not None]
        if not route_ids:
            return state

        all_stops = db.query(RouteStop).filter(RouteStop.route_id.in_(route_ids)).all()

        for route in routes:
            state[route.route_id] = {
                "version": route.version,
                "stops": [
                    {
                        "stop_id": s.stop_id,
                        "trip_id": s.trip_id,
                        "sequence": s.sequence,
                        "stop_type": s.stop_type,
                        "address": s.address,
                        "latitude": s.latitude,
                        "longitude": s.longitude,
                        "eta": s.eta,
                        "status": s.status,
                        "window_start": s.window_start,
                        "window_end": s.window_end,
                        "weather_condition": s.weather_condition,
                        "weather_updated_at": s.weather_updated_at,
                    }
                    for s in all_stops
                    if s.route_id == route.route_id
                ],
            }

            # Capture trip route assignments
            for stop in state[route.route_id]["stops"]:
                if stop["trip_id"]:
                    trip = db.get(Trip, stop["trip_id"])
                    if trip:
                        state[f"trip_{stop['trip_id']}"] = trip.route_id

        return state

    def _serialize_plan(self, db: Session, routes: list[Route]) -> dict:
        """Serialize the current plan into a JSON-safe before/after snapshot.

        Shape: {route_id: {name, vehicle_id, stops: [{stop_id, trip_id,
        sequence, stop_type, address, latitude, longitude}]}}
        Consumed by the Live Ops LNS impact panel.
        """
        plan: dict = {}
        for route in routes:
            stops = sorted(route.stops, key=lambda s: s.sequence)
            plan[str(route.route_id)] = {
                "name": route.name,
                "vehicle_id": route.vehicle_id,
                "stops": [
                    {
                        "stop_id": str(s.stop_id),
                        "trip_id": s.trip_id,
                        "sequence": s.sequence,
                        "stop_type": s.stop_type,
                        "address": s.address,
                        "latitude": s.latitude,
                        "longitude": s.longitude,
                    }
                    for s in stops
                ],
            }
        return plan

    def _rollback_to_state(self, db: Session, original_state: dict) -> None:
        """Rollback routes and trips to original state, restoring any RouteStop
        rows that the destroy phase deleted."""
        for key, value in original_state.items():
            if isinstance(key, str) and key.startswith("trip_"):
                trip_id = key[5:]
                trip = db.get(Trip, trip_id)
                if trip:
                    trip.route_id = value
                    db.add(trip)
                continue

            route = db.get(Route, key)
            if route is None:
                continue

            route.version = value.get("version", route.version)
            db.add(route)

            snapshot_ids = {s["stop_id"] for s in value.get("stops", [])}

            # Remove stops created during the destroy/repair phases (not part
            # of the original state) so rollback cannot leave duplicates.
            for s in db.query(RouteStop).filter(RouteStop.route_id == route.route_id).all():
                if s.stop_id not in snapshot_ids:
                    db.delete(s)
            db.flush()

            # Restore any stops that were deleted during the destroy phase.
            existing_ids = {
                s.stop_id
                for s in db.query(RouteStop).filter(RouteStop.route_id == route.route_id).all()
            }
            for snapshot in value.get("stops", []):
                if snapshot["stop_id"] not in existing_ids:
                    db.add(RouteStop(
                        # Preserve the original PK so a rollback restores the
                        # plan bit-for-bit (snapshots stay comparable).
                        stop_id=snapshot["stop_id"],
                        route_id=route.route_id,
                        trip_id=snapshot.get("trip_id"),
                        sequence=snapshot.get("sequence", 1),
                        stop_type=snapshot.get("stop_type", "waypoint"),
                        address=snapshot.get("address"),
                        latitude=snapshot.get("latitude"),
                        longitude=snapshot.get("longitude"),
                        eta=snapshot.get("eta"),
                        status=snapshot.get("status", "pending"),
                        window_start=snapshot.get("window_start"),
                        window_end=snapshot.get("window_end"),
                        weather_condition=snapshot.get("weather_condition"),
                        weather_updated_at=snapshot.get("weather_updated_at"),
                    ))
                else:
                    # Restore sequence on the surviving row
                    existing = db.query(RouteStop).filter(
                        RouteStop.route_id == route.route_id,
                        RouteStop.stop_id == snapshot["stop_id"],
                    ).one_or_none()
                    if existing:
                        existing.sequence = snapshot.get("sequence", existing.sequence)
                        db.add(existing)


# Default instances for different strategies
lns_optimizer = LNSOptimizer()
lns_optimizer_regret3 = LNSOptimizer(repair_strategy=LNSRepairStrategy.REGRET_3)