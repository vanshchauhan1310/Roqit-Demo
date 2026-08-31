"""Candidate route search with spatial and attribute filtering."""

from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from app.models.route import Route, RouteStop
from app.models.trip import Trip
from app.models.vehicle import Vehicle
from app.models.driver import Driver


@dataclass
class CandidateRoute:
    """A candidate route with metadata for optimization."""
    route: Route
    vehicle: Optional[Vehicle]
    driver: Optional[Driver]
    remaining_capacity_kg: float
    distance_to_pickup_km: float
    score: float  # Combined suitability score (higher = better)


class CandidateSearch:
    """Finds feasible candidate routes for a new trip."""

    def __init__(
        self,
        max_candidates: int = 50,
        max_pickup_distance_km: float = 50.0,
        min_capacity_buffer: float = 0.1,  # 10% buffer
    ):
        self.max_candidates = max_candidates
        self.max_pickup_distance_km = max_pickup_distance_km
        self.min_capacity_buffer = min_capacity_buffer

    def find_candidates(
        self,
        db: Session,
        trip: Trip,
    ) -> list[CandidateRoute]:
        """Find candidate routes for a new trip.

        Applies multi-stage filtering:
        1. Route status (PLANNED, ACTIVE)
        2. Vehicle compatibility
        3. Capacity availability
        4. Geographic proximity (PostGIS)
        5. Time feasibility
        6. Direction compatibility
        """
        # Stage 1: Get routes with compatible status
        query = db.query(Route).filter(
            Route.status.in_(["planned", "active", "in-transit"])
        )

        # Join vehicle and driver
        routes = query.all()

        candidates = []
        for route in routes:
            candidate = self._evaluate_candidate(db, route, trip)
            if candidate:
                candidates.append(candidate)

        # Sort by score (descending) and limit
        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates[:self.max_candidates]

    def _evaluate_candidate(
        self,
        db: Session,
        route: Route,
        trip: Trip,
    ) -> Optional[CandidateRoute]:
        """Evaluate a single route as a candidate."""
        # Get vehicle
        vehicle = db.get(Vehicle, route.vehicle_id) if route.vehicle_id else None
        if not vehicle:
            return None

        # Get driver
        driver = db.get(Driver, route.driver_id) if route.driver_id else None

        # Stage 2: Vehicle compatibility
        if trip.vehicle_type and vehicle.vehicle_type != trip.vehicle_type:
            return None

        # Stage 3: Capacity check
        remaining_capacity = self._calculate_remaining_capacity(db, route, vehicle)
        if remaining_capacity < (trip.load_weight_kg or 0) * (1 + self.min_capacity_buffer):
            return None

        # Stage 4: Geographic proximity
        distance_to_pickup = self._calculate_pickup_distance(route, trip)
        if distance_to_pickup > self.max_pickup_distance_km:
            return None

        # Stage 5: Time feasibility (basic check)
        if not self._check_time_feasibility(route, trip):
            return None

        # Stage 6: Direction compatibility
        if not self._check_direction_compatibility(route, trip):
            return None

        # Calculate composite score
        score = self._calculate_score(
            remaining_capacity=remaining_capacity,
            distance_to_pickup=distance_to_pickup,
            vehicle=vehicle,
            driver=driver,
            route=route,
        )

        return CandidateRoute(
            route=route,
            vehicle=vehicle,
            driver=driver,
            remaining_capacity_kg=remaining_capacity,
            distance_to_pickup_km=distance_to_pickup,
            score=score,
        )

    def _calculate_remaining_capacity(
        self,
        db: Session,
        route: Route,
        vehicle: Vehicle,
    ) -> float:
        """Calculate remaining vehicle capacity in kg."""
        if vehicle.load_capacity_kg is None:
            return float('inf')

        current_load = 0.0
        for stop in route.stops:
            if stop.trip_id and stop.stop_type == "pickup":
                trip = db.get(Trip, stop.trip_id)
                if trip and trip.load_weight_kg:
                    current_load += trip.load_weight_kg

        return vehicle.load_capacity_kg - current_load

    def _calculate_pickup_distance(
        self,
        route: Route,
        trip: Trip,
    ) -> float:
        """Calculate distance from route's current position to trip pickup."""
        # Use route's current location or last stop
        if route.current_lat is not None and route.current_lon is not None:
            return self._haversine_km(
                route.current_lat, route.current_lon,
                trip.gps_start_lat, trip.gps_start_lon
            )

        # Fallback: use last geocoded stop
        geocoded_stops = [s for s in route.stops if s.latitude and s.longitude]
        if geocoded_stops:
            last_stop = max(geocoded_stops, key=lambda s: s.sequence)
            return self._haversine_km(
                last_stop.latitude, last_stop.longitude,
                trip.gps_start_lat, trip.gps_start_lon
            )

        # No location info - return large distance
        return float('inf')

    def _check_time_feasibility(
        self,
        route: Route,
        trip: Trip,
    ) -> bool:
        """Basic time feasibility check."""
        # TODO: Implement proper time window checking
        return True

    def _check_direction_compatibility(
        self,
        route: Route,
        trip: Trip,
    ) -> bool:
        """Check if trip direction is compatible with route's general direction."""
        # TODO: Implement direction compatibility using bearing/heading
        return True

    def _calculate_score(
        self,
        remaining_capacity: float,
        distance_to_pickup: float,
        vehicle: Vehicle,
        driver: Optional[Driver],
        route: Route,
    ) -> float:
        """Calculate composite suitability score (higher = better)."""
        score = 0.0

        # Capacity utilization (prefer routes with some space but not too empty)
        if remaining_capacity > 0:
            utilization = 1.0 - (remaining_capacity / (vehicle.load_capacity_kg or 1))
            score += utilization * 30  # 0-30 points

        # Distance to pickup (closer is better)
        if distance_to_pickup < float('inf'):
            distance_score = max(0, 30 - distance_to_pickup * 0.5)  # ~60km = 0 points
            score += distance_score

        # Driver quality
        if driver:
            # Lower rating risk is better (proxy for reliability)
            rating = driver.rating or 3.0
            delay_score = max(0.0, (5.0 - rating) / 5.0) * 20
            score += delay_score
            # Experience bonus
            exp_score = min((driver.experience_years or 0) / 10.0, 1.0) * 10
            score += exp_score

        # Route efficiency (fewer stops = more flexibility)
        stop_count = len([s for s in route.stops if s.stop_type in ("pickup", "delivery")])
        if stop_count > 0:
            score += max(0, 20 - stop_count * 2)

        return score

    @staticmethod
    def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate distance between two points in km."""
        from math import radians, sin, cos, sqrt, atan2
        R = 6371.0

        lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
        dlat = lat2 - lat1
        dlon = lon2 - lon1

        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
        c = 2 * atan2(sqrt(a), sqrt(1-a))
        return R * c


# Global instance
candidate_search = CandidateSearch()