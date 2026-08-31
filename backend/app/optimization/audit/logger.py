"""Audit logger for optimization operations.

Persists every greedy assignment, new-route creation, failed assignment and
LNS run to the `route_assignments` and `optimization_runs` tables so all
optimization decisions are traceable, while still mirroring to stdout.
"""

import uuid
from typing import Optional

from sqlalchemy.orm import Session

from app.models.route import Route
from app.models.trip import Trip
from app.models.optimization_audit import RouteAssignment, OptimizationRun


class OptimizationAuditLogger:
    """Logs all optimization decisions for traceability."""

    def log_greedy_assignment(
        self,
        db: Session,
        trip: Trip,
        route: Optional[Route],
        insertion_position: int,
        cost: float,
        distance_delta: float,
        duration_delta: float,
        delay_delta: float,
        algorithm_version: str = "greedy-v1",
        feasible: bool = True,
        violations: Optional[list[str]] = None,
    ) -> None:
        """Log a greedy assignment decision (persisted + stdout)."""
        if route is not None:
            db.add(RouteAssignment(
                trip_id=trip.trip_id,
                route_id=route.route_id,
                assignment_status="ASSIGNED",
                insertion_position=insertion_position,
                additional_distance_km=distance_delta,
                additional_duration_minutes=duration_delta,
                delay_impact_minutes=delay_delta,
                delay_risk=0.0,
                change_penalty=0.0,
                score=cost,
                reason="; ".join(violations or []),
                algorithm="GREEDY_BEST_INSERTION",
                algorithm_version=algorithm_version,
            ))
        db.add(OptimizationRun(
            optimization_type="ONLINE_GREEDY",
            trip_id=trip.trip_id,
            candidate_routes_count=0,
            feasible_routes_count=1 if feasible else 0,
            routes_affected=1 if route is not None else 0,
            old_cost=None,
            new_cost=cost,
            improvement=None,
            execution_time_ms=0,
            algorithm_version=algorithm_version,
            status="completed" if feasible else "failed",
        ))
        db.commit()

        print(f"[AUDIT] GREEDY_ASSIGNMENT trip={trip.trip_id} "
              f"route={route.route_id if route else 'NEW'} "
              f"cost={cost:.2f} dist_delta={distance_delta:.2f} "
              f"dur_delta={duration_delta:.2f} delay_delta={delay_delta:.2f} "
              f"feasible={feasible} version={algorithm_version}")

    def log_new_route_created(
        self,
        db: Session,
        trip: Trip,
        route: Route,
        vehicle_id: str,
        driver_id: Optional[str],
        algorithm_version: str = "greedy-v1",
    ) -> None:
        """Log new route creation (persisted + stdout)."""
        db.add(RouteAssignment(
            trip_id=trip.trip_id,
            route_id=route.route_id,
            assignment_status="NEW_ROUTE",
            insertion_position=1,
            score=0.0,
            algorithm="NEW_ROUTE",
            algorithm_version=algorithm_version,
        ))
        db.add(OptimizationRun(
            optimization_type="ONLINE_GREEDY",
            trip_id=trip.trip_id,
            candidate_routes_count=0,
            feasible_routes_count=1,
            routes_affected=1,
            old_cost=None,
            new_cost=0.0,
            improvement=None,
            execution_time_ms=0,
            algorithm_version=algorithm_version,
            status="completed",
        ))
        db.commit()

        print(f"[AUDIT] NEW_ROUTE_CREATED trip={trip.trip_id} "
              f"route={route.route_id} vehicle={vehicle_id} "
              f"driver={driver_id} version={algorithm_version}")

    def log_lns_run(
        self,
        db: Session,
        run_id: Optional[uuid.UUID],
        old_cost: float,
        new_cost: float,
        improvement: float,
        routes_affected: int,
        trips_reinserted: int,
        execution_time_ms: int,
        destroy_strategy: str,
        repair_strategy: str,
        accepted: bool,
        routes_before: Optional[dict] = None,
        routes_after: Optional[dict] = None,
    ) -> None:
        """Log LNS optimization run (persisted + stdout).

        routes_before / routes_after carry full per-route stop snapshots so
        the UI can render a Before ⇄ After impact comparison.
        """
        db.add(OptimizationRun(
            optimization_type="TRIGGERED_LNS" if run_id else "PERIODIC_LNS",
            trip_id=None,
            candidate_routes_count=0,
            feasible_routes_count=0,
            routes_affected=routes_affected,
            old_cost=old_cost,
            new_cost=new_cost,
            improvement=improvement,
            execution_time_ms=execution_time_ms,
            trips_reinserted=trips_reinserted,
            destroy_strategy=destroy_strategy,
            repair_strategy=repair_strategy,
            routes_before=routes_before,
            routes_after=routes_after,
            algorithm_version="lns-v1",
            status="completed" if accepted else "rolled_back",
        ))
        db.commit()

        print(f"[AUDIT] LNS_RUN run_id={run_id or 'N/A'} "
              f"old_cost={old_cost:.2f} new_cost={new_cost:.2f} "
              f"improvement={improvement:.2f} accepted={accepted} "
              f"routes_affected={routes_affected} trips_reinserted={trips_reinserted} "
              f"time_ms={execution_time_ms} destroy={destroy_strategy} "
              f"repair={repair_strategy} "
              f"snapshots={'yes' if routes_before and routes_after else 'no'}")

    def log_route_freeze(
        self,
        db: Session,
        route: Route,
        frozen_until_sequence: int,
        reason: str,
    ) -> None:
        """Log route freeze event."""
        print(f"[AUDIT] ROUTE_FREEZE route={route.route_id} "
              f"frozen_until={frozen_until_sequence} reason={reason}")

    def log_concurrency_conflict(
        self,
        db: Session,
        route_id: uuid.UUID,
        expected_version: int,
        actual_version: int,
        operation: str,
    ) -> None:
        """Log optimistic locking conflict."""
        print(f"[AUDIT] CONCURRENCY_CONFLICT route={route_id} "
              f"expected_version={expected_version} actual_version={actual_version} "
              f"operation={operation}")

    def log_assignment_failed(
        self,
        db: Session,
        trip: Trip,
        reason: str,
        candidate_count: int,
        feasible_count: int,
        algorithm_version: str = "greedy-v1",
    ) -> None:
        """Log failed assignment (persisted + stdout)."""
        db.add(OptimizationRun(
            optimization_type="ONLINE_GREEDY",
            trip_id=trip.trip_id,
            candidate_routes_count=candidate_count,
            feasible_routes_count=feasible_count,
            routes_affected=0,
            old_cost=None,
            new_cost=None,
            improvement=None,
            execution_time_ms=0,
            algorithm_version=algorithm_version,
            status="failed",
        ))
        db.commit()

        print(f"[AUDIT] ASSIGNMENT_FAILED trip={trip.trip_id} "
              f"reason={reason} candidates={candidate_count} feasible={feasible_count}")


# Global instance
audit_logger = OptimizationAuditLogger()