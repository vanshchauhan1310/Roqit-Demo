"""Cost function for route optimization.

Computes weighted cost combining distance, time, delay, fuel, risk, and change penalty.
"""

from dataclasses import dataclass, field
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.route import Route, RouteStop
from app.models.trip import Trip
from app.models.vehicle import Vehicle
from app.services.fuel_cost_service import get_fuel_cost_estimate


@dataclass
class CostWeights:
    """Configurable weights for cost function components."""
    distance: float = 0.30
    time: float = 0.25
    delay: float = 0.20
    fuel: float = 0.10
    risk: float = 0.10
    change: float = 0.05

    def normalize(self) -> "CostWeights":
        """Return normalized weights summing to 1.0."""
        total = self.distance + self.time + self.delay + self.fuel + self.risk + self.change
        if total == 0:
            return CostWeights()
        return CostWeights(
            distance=self.distance / total,
            time=self.time / total,
            delay=self.delay / total,
            fuel=self.fuel / total,
            risk=self.risk / total,
            change=self.change / total,
        )


@dataclass
class CostComponents:
    """Individual cost components for transparency."""
    extra_distance_km: float = 0.0
    extra_duration_minutes: float = 0.0
    delay_impact_minutes: float = 0.0
    fuel_cost_rupees: float = 0.0
    delay_risk: float = 0.0
    route_change_penalty: float = 0.0

    def total(self, weights: CostWeights) -> float:
        """Compute weighted total cost."""
        return (
            weights.distance * self.extra_distance_km +
            weights.time * self.extra_duration_minutes +
            weights.delay * self.delay_impact_minutes +
            weights.fuel * self.fuel_cost_rupees +
            weights.risk * self.delay_risk +
            weights.change * self.route_change_penalty
        )


@dataclass
class InsertionCostResult:
    """Result of cost calculation for an insertion."""
    cost: float
    components: CostComponents
    feasible: bool = True
    violations: list[str] = field(default_factory=list)


class CostFunction:
    """Calculates insertion cost for route optimization."""

    def __init__(self, weights: Optional[CostWeights] = None):
        self.weights = (weights or CostWeights()).normalize()

    def calculate_insertion_cost(
        self,
        db: Session,
        route: Route,
        original_stops: list[RouteStop],
        new_stops: list[RouteStop],
        trip: Trip,
        vehicle: Optional[Vehicle] = None,
    ) -> InsertionCostResult:
        """Calculate cost of inserting a trip into a route at a specific position.

        Args:
            db: Database session
            route: The route being modified
            original_stops: Stops before insertion
            new_stops: Stops after insertion
            trip: The trip being inserted
            vehicle: The vehicle assigned to route

        Returns:
            InsertionCostResult with total cost and component breakdown
        """
        components = CostComponents()

        # 1. Extra distance
        components.extra_distance_km = self._calculate_extra_distance(
            db, original_stops, new_stops
        )

        # 2. Extra duration
        components.extra_duration_minutes = self._calculate_extra_duration(
            db, original_stops, new_stops
        )

        # 3. Delay impact
        components.delay_impact_minutes = self._calculate_delay_impact(
            db, route, original_stops, new_stops
        )

        # 4. Fuel cost
        if vehicle:
            components.fuel_cost_rupees = self._calculate_fuel_cost(
                db, original_stops, new_stops, vehicle
            )

        # 5. Delay risk (based on traffic, weather, driver history)
        components.delay_risk = self._calculate_delay_risk(route, trip)

        # 6. Route change penalty (discourage unnecessary changes)
        components.route_change_penalty = self._calculate_change_penalty(
            route, original_stops, new_stops
        )

        total_cost = components.total(self.weights)

        return InsertionCostResult(
            cost=total_cost,
            components=components,
        )

    def _calculate_extra_distance(
        self,
        db: Session,
        original_stops: list[RouteStop],
        new_stops: list[RouteStop],
    ) -> float:
        """Calculate additional distance in km."""
        orig_dist = self._calculate_total_distance(db, original_stops)
        new_dist = self._calculate_total_distance(db, new_stops)
        return max(0.0, new_dist - orig_dist)

    def _calculate_extra_duration(
        self,
        db: Session,
        original_stops: list[RouteStop],
        new_stops: list[RouteStop],
    ) -> float:
        """Calculate additional duration in minutes."""
        orig_dur = self._calculate_total_duration(db, original_stops)
        new_dur = self._calculate_total_duration(db, new_stops)
        return max(0.0, (new_dur - orig_dur) / 60.0)  # convert to minutes

    def _calculate_delay_impact(
        self,
        db: Session,
        route: Route,
        original_stops: list[RouteStop],
        new_stops: list[RouteStop],
    ) -> float:
        """Calculate delay impact on existing stops in minutes."""
        # Compare ETAs before and after for existing stops
        # For simplicity, return 0 for now - implement with actual ETA comparison
        return 0.0

    def _calculate_fuel_cost(
        self,
        db: Session,
        original_stops: list[RouteStop],
        new_stops: list[RouteStop],
        vehicle: Vehicle,
    ) -> float:
        """Calculate additional fuel cost in rupees."""
        extra_distance = self._calculate_extra_distance(db, original_stops, new_stops)
        if extra_distance <= 0:
            return 0.0

        # Use vehicle fuel efficiency (defensive: the real vehicle_master table has
        # no fuel_price_per_l column, so fall back to the configured default).
        kmpl = vehicle.avg_kmpl_rated or 8.5
        fuel_price = getattr(vehicle, "fuel_price_per_l", None) or 92.5
        fuel_liters = extra_distance / kmpl
        return fuel_liters * fuel_price

    def _calculate_delay_risk(
        self,
        route: Route,
        trip: Trip,
    ) -> float:
        """Calculate delay risk score (0-1)."""
        risk = 0.0

        # Traffic density factor
        traffic_risk = {"Low": 0.1, "Medium": 0.3, "High": 0.6}.get(trip.traffic_density, 0.3)
        risk += traffic_risk * 0.4

        # Weather factor
        weather_risk = {"Clear": 0.0, "Clouds": 0.1, "Rain": 0.4, "Storm": 0.8}.get(
            trip.weather_condition, 0.1
        )
        risk += weather_risk * 0.3

        # Driver quality risk (proxy: low rating => higher risk)
        if route.driver:
            rating = route.driver.rating or 3.0
            driver_risk = max(0.0, (5.0 - rating) / 5.0)
            risk += driver_risk * 0.3

        return min(risk, 1.0)

    def _calculate_change_penalty(
        self,
        route: Route,
        original_stops: list[RouteStop],
        new_stops: list[RouteStop],
    ) -> float:
        """Calculate penalty for changing existing route structure."""
        # Penalize reordering of existing stops
        orig_sequences = [s.sequence for s in original_stops if s.trip_id]
        new_sequences = [s.sequence for s in new_stops if s.trip_id and s.trip_id in {o.trip_id for o in original_stops}]

        if len(orig_sequences) != len(new_sequences):
            return 10.0  # High penalty if trip count changes unexpectedly

        # Count position changes
        changes = sum(1 for o, n in zip(orig_sequences, new_sequences) if o != n)
        return float(changes) * 2.0

    def _calculate_total_distance(
        self,
        db: Session,
        stops: list[RouteStop],
    ) -> float:
        """Calculate total route distance in km."""
        geocoded = [s for s in stops if s.latitude is not None and s.longitude is not None]
        if len(geocoded) < 2:
            return 0.0

        total = 0.0
        for prev, stop in zip(geocoded, geocoded[1:]):
            # Use OSRM or haversine as fallback
            from math import radians, sin, cos, sqrt, atan2
            R = 6371.0  # Earth radius in km

            lat1, lon1 = radians(prev.latitude), radians(prev.longitude)
            lat2, lon2 = radians(stop.latitude), radians(stop.longitude)

            dlat = lat2 - lat1
            dlon = lon2 - lon1

            a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
            c = 2 * atan2(sqrt(a), sqrt(1-a))
            total += R * c

        return total

    def _calculate_total_duration(
        self,
        db: Session,
        stops: list[RouteStop],
    ) -> float:
        """Calculate total route duration in seconds.

        Pure, synchronous, network-free estimate: haversine distance divided by
        an assumed average speed. The greedy-insertion loop evaluates O(n^2)
        candidate positions, each over the whole route, so making per-leg OSRM
        calls here would turn every assignment into dozens/hundreds of network
        round-trips. Road-accurate durations are computed where they matter:
        the async eta/route services used for display and ETA forecasting.
        """
        from math import radians, sin, cos, sqrt, atan2
        R = 6371.0  # Earth radius in km
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


# Default instance
cost_function = CostFunction()