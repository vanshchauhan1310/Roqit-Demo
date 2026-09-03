"""Feasibility Engine for route optimization.

Validates hard constraints before accepting any route modification.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, TYPE_CHECKING
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.route import Route, RouteStop
from app.models.trip import Trip
from app.models.vehicle import Vehicle
from app.optimization.state import (
    ACTIVE_STATUSES,
    MAX_DRIVER_HOS_HOURS,
    duty_window_start,
    estimate_route_hours,
    vehicle_active_load_kg,
)

if TYPE_CHECKING:
    from app.models.driver import Driver


@dataclass
class Violation:
    """Represents a feasibility violation."""
    type: str
    message: str
    severity: str = "hard"  # "hard" or "soft"


@dataclass
class FeasibilityResult:
    """Result of feasibility check."""
    feasible: bool
    violations: list[Violation]

    def add_violation(self, violation_type: str, message: str, severity: str = "hard") -> None:
        self.violations.append(Violation(violation_type, message, severity))
        if severity == "hard":
            self.feasible = False


class FeasibilityEngine:
    """Validates route modifications against hard constraints."""

    def __init__(
        self,
        max_route_duration_hours: float = 12.0,
        max_detour_factor: float = 1.5,
        max_delay_minutes: int = 60,
        max_wait_minutes: int = 30,
    ):
        self.max_route_duration_hours = max_route_duration_hours
        self.max_detour_factor = max_detour_factor
        self.max_delay_minutes = max_delay_minutes
        self.max_wait_minutes = max_wait_minutes

    def check_route_feasibility(
        self,
        db: Session,
        route: Route,
        new_stops: list[RouteStop],
        trip: Trip,
        vehicle: Optional[Vehicle] = None,
        driver: Optional["Driver"] = None,
    ) -> FeasibilityResult:
        """Complete feasibility check for inserting a trip into a route."""
        result = FeasibilityResult(feasible=True, violations=[])

        # 1. Capacity check
        self._check_capacity(db, route, trip, vehicle, result)

        # 2. Vehicle compatibility
        self._check_vehicle_compatibility(route, trip, vehicle, result)

        # 3. Driver constraints
        self._check_driver_constraints(db, route, new_stops, trip, driver, result)

        # 4. Route duration
        self._check_route_duration(db, route, new_stops, result)

        # 5. Time windows
        self._check_time_windows(db, route, new_stops, trip, result)

        # 6. Delivery commitments (frozen stops)
        self._check_frozen_stops(route, new_stops, result)

        # 7. Maximum delay impact
        self._check_delay_impact(db, route, new_stops, trip, result)

        # 8. Detour factor
        self._check_detour_factor(db, route, new_stops, trip, result)

        # 9. Pickup before delivery precedence
        self._check_precedence(new_stops, result)

        # 10. Geographic compatibility (basic)
        self._check_geographic_compatibility(route, trip, result)

        return result

    def _check_capacity(
        self,
        db: Session,
        route: Route,
        trip: Trip,
        vehicle: Optional[Vehicle],
        result: FeasibilityResult,
    ) -> None:
        """Check if vehicle has capacity for new trip.

        The hard capacity constraint is the vehicle's AGGREGATE active load
        across all of its active routes, not just the load on the candidate
        route - a vehicle serving 3 routes each under its capacity can still
        be over-capacity overall. Load is derived from authoritative
        RouteStop/Trip rows, never from cached capacity columns.
        """
        if vehicle is None:
            return

        current_load = vehicle_active_load_kg(db, vehicle)
        new_load = trip.load_weight_kg or 0
        cap = vehicle.load_capacity_kg
        if cap is not None and current_load + new_load > cap:
            result.add_violation(
                "CAPACITY",
                f"Vehicle aggregate capacity exceeded: {current_load + new_load} kg > {cap} kg"
            )

    def _check_vehicle_compatibility(
        self,
        route: Route,
        trip: Trip,
        vehicle: Optional[Vehicle],
        result: FeasibilityResult,
    ) -> None:
        """Check vehicle type compatibility with trip requirements."""
        if vehicle is None or vehicle.vehicle_type is None:
            return

        if trip.vehicle_type and trip.vehicle_type != vehicle.vehicle_type:
            result.add_violation(
                "VEHICLE_TYPE_MISMATCH",
                f"Trip requires {trip.vehicle_type}, vehicle is {vehicle.vehicle_type}"
            )

    def _check_driver_constraints(
        self,
        db: Session,
        route: Route,
        new_stops: list[RouteStop],
        trip: Trip,
        driver: Optional["Driver"],
        result: FeasibilityResult,
    ) -> None:
        """Check driver constraints (license, HOS, etc.)."""
        if driver is None:
            return

        # Check license type compatibility (only when the trip actually has one)
        trip_license = getattr(trip, "license_type", None)
        if trip_license and driver.license_type != trip_license:
            result.add_violation(
                "LICENSE_MISMATCH",
                f"Trip requires {trip_license}, driver has {driver.license_type}"
            )

        # Hours-of-service: reject if inserting this trip would push the
        # driver past MAX_DRIVER_HOS_HOURS. The candidate route is excluded
        # from the driver's current-hours sum (its projected duration already
        # includes the new trip via ``new_stops``) so the current route's
        # baseline is not double-counted. Uses the SHARED duration estimator
        # (state.estimate_route_hours - travel + per-stop service time) so the
        # insertion path, the new-route path, and the audit agree on hours.
        other_hours = self._driver_active_hours(
            db, driver.driver_id, exclude_route_id=route.route_id
        )
        candidate_route_hours = estimate_route_hours(new_stops)
        projected_hours = other_hours + candidate_route_hours
        if projected_hours > MAX_DRIVER_HOS_HOURS:
            result.add_violation(
                "DRIVER_HOS",
                f"Driver hours-of-service exceeded: {projected_hours:.1f}h > "
                f"{MAX_DRIVER_HOS_HOURS:.1f}h limit"
            )

    def _driver_active_hours(
        self,
        db: Session,
        driver_id: str,
        exclude_route_id=None,
    ) -> float:
        """Estimated hours already assigned to a driver's active routes,
        excluding the candidate route (whose duration is evaluated via the
        projected stop list). Uses the existing haversine route-duration
        calculation."""
        # autoflush=False would hide same-session route/stop insertions from
        # the queries below, under-counting committed hours (see state.py).
        if db.new or db.dirty:
            db.flush()
        routes = db.query(Route).filter(
            Route.driver_id == driver_id,
            Route.status.in_(ACTIVE_STATUSES),
            # Rolling duty window: hours from older routes don't count against
            # the driver's current 14h clock (see state.DUTY_WINDOW_HOURS).
            Route.created_at >= duty_window_start(),
        ).all()
        total_hours = 0.0
        for r in routes:
            if exclude_route_id is not None and r.route_id == exclude_route_id:
                continue
            stops = db.query(RouteStop).filter(RouteStop.route_id == r.route_id).all()
            total_hours += estimate_route_hours(stops)
        return total_hours

    def _check_route_duration(
        self,
        db: Session,
        route: Route,
        new_stops: list[RouteStop],
        result: FeasibilityResult,
    ) -> None:
        """Check if route duration exceeds maximum allowed."""
        # Calculate total route duration with new stops
        total_duration = self._calculate_route_duration(db, new_stops)
        if total_duration > self.max_route_duration_hours * 3600:  # convert to seconds
            result.add_violation(
                "ROUTE_DURATION",
                f"Route duration {total_duration/3600:.1f}h exceeds maximum {self.max_route_duration_hours}h"
            )

    def _check_time_windows(
        self,
        db: Session,
        route: Route,
        new_stops: list[RouteStop],
        trip: Trip,
        result: FeasibilityResult,
    ) -> None:
        """Check time window constraints for all stops."""
        # TODO: Implement time window validation
        # Check each stop's window_start/window_end against computed ETA
        pass

    def _check_frozen_stops(
        self,
        route: Route,
        new_stops: list[RouteStop],
        result: FeasibilityResult,
    ) -> None:
        """Check that frozen stops are not being modified."""
        frozen_until = route.frozen_until_sequence or 0
        for stop in new_stops:
            if stop.sequence <= frozen_until:
                result.add_violation(
                    "FROZEN_STOP_VIOLATION",
                    f"Stop at sequence {stop.sequence} is frozen (frozen_until_sequence={frozen_until})"
                )

    def _check_delay_impact(
        self,
        db: Session,
        route: Route,
        new_stops: list[RouteStop],
        trip: Trip,
        result: FeasibilityResult,
    ) -> None:
        """Check if insertion causes excessive delay to existing stops."""
        # TODO: Compare ETAs before/after insertion
        pass

    def _check_detour_factor(
        self,
        db: Session,
        route: Route,
        new_stops: list[RouteStop],
        trip: Trip,
        result: FeasibilityResult,
    ) -> None:
        """Check if insertion causes excessive detour."""
        # TODO: Compare direct distance vs route distance for new trip
        pass

    def _check_precedence(
        self,
        new_stops: list[RouteStop],
        result: FeasibilityResult,
    ) -> None:
        """Ensure pickup comes before delivery for each trip."""
        by_trip = {}
        for stop in new_stops:
            if stop.trip_id and stop.stop_type in ("pickup", "delivery"):
                by_trip.setdefault(stop.trip_id, {})[stop.stop_type] = stop

        for trip_id, pair in by_trip.items():
            if "pickup" in pair and "delivery" in pair:
                if pair["pickup"].sequence > pair["delivery"].sequence:
                    result.add_violation(
                        "PRECEDENCE_VIOLATION",
                        f"Delivery before pickup for trip {trip_id}"
                    )

    def _check_geographic_compatibility(
        self,
        route: Route,
        trip: Trip,
        result: FeasibilityResult,
    ) -> None:
        """Basic geographic compatibility check."""
        # If route has no stops yet, it's compatible
        if not route.stops:
            return

        # Check if new trip is in completely different region
        # For now, just a placeholder - in production use PostGIS distance
        pass

    def _calculate_route_duration(
        self,
        db: Session,
        stops: list[RouteStop],
    ) -> float:
        """Calculate total route duration in seconds.

        Network-free haversine estimate (see cost_function for rationale) —
        this runs for every candidate insertion position.
        """
        from math import radians, sin, cos, sqrt, atan2
        R = 6371.0
        AVG_SPEED_KPH = 40.0

        geocoded = [s for s in stops if s.latitude is not None and s.longitude is not None]
        if len(geocoded) < 2:
            return 0.0

        total = 0.0
        for prev, stop in zip(geocoded, geocoded[1:]):
            lat1, lon1 = radians(prev.latitude), radians(prev.longitude)
            lat2, lon2 = radians(stop.latitude), radians(stop.longitude)
            dlat = lat2 - lat1
            dlon = lon2 - lon1
            a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
            c = 2 * atan2(sqrt(a), sqrt(1 - a))
            dist_km = R * c
            total += (dist_km / AVG_SPEED_KPH) * 3600

        return total


# Global instance
feasibility_engine = FeasibilityEngine()