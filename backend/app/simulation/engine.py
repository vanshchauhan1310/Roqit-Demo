"""Simulation engine for benchmarking the optimization algorithms."""

import csv
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.trip import Trip
from app.models.route import Route, RouteStop
from app.models.vehicle import Vehicle
from app.workers.trip_assignment_worker import TripAssignmentWorker
from app.workers.lns_worker import LNSWorker
from app.optimization.greedy.insertion import greedy_insertion
from app.optimization.candidates.search import candidate_search
from app.optimization.feasibility.engine import feasibility_engine
from app.optimization.scoring.cost_function import cost_function
from app.optimization.lns.optimizer import LNSOptimizer
from app.optimization.audit.logger import audit_logger


@dataclass
class SimulationResult:
    """Results from a simulation run."""
    trips_processed: int = 0
    trips_assigned: int = 0
    trips_unassigned: int = 0
    routes_created: int = 0
    total_distance_km: float = 0.0
    total_duration_minutes: float = 0.0
    avg_distance_per_trip: float = 0.0
    avg_delay_minutes: float = 0.0
    total_fuel_cost: float = 0.0
    route_utilization: float = 0.0
    greedy_cost: float = 0.0
    final_lns_cost: float = 0.0
    improvement_percentage: float = 0.0
    assignment_latency_ms: float = 0.0


class SimulationEngine:
    """Replays historical trip data through the optimization pipeline."""

    def __init__(self):
        self.assignment_worker = TripAssignmentWorker()
        self.lns_worker = LNSWorker()
        self.db = SessionLocal()

    def run_from_csv(
        self,
        csv_path: str,
        timestamp_column: str = "scheduled_start",
        speed_factor: float = 1.0,  # 1.0 = real-time, >1 = faster
        run_lns_every_n_trips: int = 0,  # 0 = don't run LNS during replay
    ) -> SimulationResult:
        """Run simulation from CSV file.

        Args:
            csv_path: Path to CSV with trip data
            timestamp_column: Column name for chronological ordering
            speed_factor: How fast to replay (1.0 = real time)
            run_lns_every_n_trips: Run LNS after every N trips (0 = disabled)

        Returns:
            SimulationResult with metrics
        """
        result = SimulationResult()

        # Read CSV
        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            trips_data = list(reader)

        # Sort by timestamp
        trips_data.sort(key=lambda x: x.get(timestamp_column, ""))

        print(f"Loaded {len(trips_data)} trips from {csv_path}")

        # Process each trip
        for i, trip_data in enumerate(trips_data):
            trip = self._create_trip_from_csv(trip_data)
            if not trip:
                continue

            # Time the assignment
            start_time = datetime.utcnow()
            success = self.assignment_worker._assign_trip(self.db, trip.trip_id)
            latency = (datetime.utcnow() - start_time).total_seconds() * 1000
            result.assignment_latency_ms += latency

            result.trips_processed += 1
            if success:
                result.trips_assigned += 1
            else:
                result.trips_unassigned += 1

            # Run LNS periodically
            if run_lns_every_n_trips > 0 and (i + 1) % run_lns_every_n_trips == 0:
                print(f"Running LNS after {i + 1} trips...")
                self.lns_worker.run_once()

            # Progress
            if (i + 1) % 100 == 0:
                print(f"Processed {i + 1}/{len(trips_data)} trips")

        # Final metrics
        self._calculate_final_metrics(result)
        return result

    def _create_trip_from_csv(self, trip_data: dict) -> Optional[Trip]:
        """Create a Trip object from CSV row."""
        try:
            trip = Trip(
                trip_id=trip_data.get("trip_ref") or trip_data.get("trip_id") or f"TRIP-{uuid.uuid4().hex[:8]}",
                origin=trip_data.get("origin") or trip_data.get("pickup_address", ""),
                destination=trip_data.get("destination") or trip_data.get("delivery_address", ""),
                gps_start_lat=float(trip_data.get("gps_start_lat", 0)),
                gps_start_lon=float(trip_data.get("gps_start_lon", 0)),
                gps_end_lat=float(trip_data.get("gps_end_lat", 0)),
                gps_end_lon=float(trip_data.get("gps_end_lon", 0)),
                planned_distance_km=float(trip_data.get("planned_distance_km", 0)) if trip_data.get("planned_distance_km") else None,
                pickup_time=datetime.fromisoformat(trip_data["pickup_time"]) if trip_data.get("pickup_time") else datetime.utcnow(),
                load_weight_kg=int(trip_data["load_weight_kg"]) if trip_data.get("load_weight_kg") else None,
                vehicle_type=trip_data.get("vehicle_type"),
                weather_condition=trip_data.get("weather_condition"),
                road_type=trip_data.get("road_type"),
                traffic_density=trip_data.get("traffic_density"),
                fuel_price_per_l=float(trip_data["fuel_price_per_l"]) if trip_data.get("fuel_price_per_l") else None,
                status="scheduled",
            )
            self.db.add(trip)
            self.db.commit()
            self.db.refresh(trip)
            return trip
        except Exception as e:
            print(f"Error creating trip from CSV: {e}")
            self.db.rollback()
            return None

    def _calculate_final_metrics(self, result: SimulationResult) -> None:
        """Calculate final metrics from database state."""
        # Count routes
        routes = self.db.query(Route).filter(Route.status != "cancelled").all()
        result.routes_created = len(routes)

        # Calculate totals
        total_distance = 0.0
        total_duration = 0.0
        total_trips = 0
        total_load = 0.0
        total_capacity = 0.0

        for route in routes:
            stops = sorted(route.stops, key=lambda s: s.sequence)
            geocoded = [s for s in stops if s.latitude and s.longitude]

            for prev, stop in zip(geocoded, geocoded[1:]):
                from math import radians, sin, cos, sqrt, atan2
                R = 6371.0
                lat1, lon1 = radians(prev.latitude), radians(prev.longitude)
                lat2, lon2 = radians(stop.latitude), radians(stop.longitude)
                dlat = lat2 - lat1
                dlon = lon2 - lon1
                a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
                c = 2 * atan2(sqrt(a), sqrt(1-a))
                total_distance += R * c

            if route.capacity_kg:
                total_capacity += route.capacity_kg
            if route.used_capacity_kg:
                total_load += route.used_capacity_kg

            # Count trips on this route
            trip_ids = set(s.trip_id for s in stops if s.trip_id)
            total_trips += len(trip_ids)

        result.total_distance_km = total_distance
        if total_trips > 0:
            result.avg_distance_per_trip = total_distance / total_trips
        if total_capacity > 0:
            result.route_utilization = total_load / total_capacity

    def run_greedy_vs_lns_comparison(self, csv_path: str) -> dict:
        """Run comparison: greedy-only vs greedy+LNS."""
        # Reset database
        self._reset_optimization_state()

        # Run with greedy only
        greedy_result = self.run_from_csv(csv_path, run_lns_every_n_trips=0)
        greedy_cost = self._calculate_total_cost()
        greedy_result.greedy_cost = greedy_cost

        # Reset again
        self._reset_optimization_state()

        # Run with greedy + LNS
        lns_result = self.run_from_csv(csv_path, run_lns_every_n_trips=50)
        lns_cost = self._calculate_total_cost()
        lns_result.final_lns_cost = lns_cost

        if greedy_cost > 0:
            lns_result.improvement_percentage = (greedy_cost - lns_cost) / greedy_cost * 100

        return {
            "greedy_only": greedy_result,
            "greedy_plus_lns": lns_result,
        }

    def _reset_optimization_state(self) -> None:
        """Reset routes and trip assignments for fresh simulation."""
        # Delete all route stops and routes
        self.db.query(RouteStop).delete()
        self.db.query(Route).delete()
        # Reset trip assignments
        self.db.query(Trip).update({Trip.route_id: None})
        self.db.commit()

    def _calculate_total_cost(self) -> float:
        """Calculate total cost of current solution."""
        routes = self.db.query(Route).filter(Route.status != "cancelled").all()
        total_cost = 0.0

        for route in routes:
            stops = sorted(route.stops, key=lambda s: s.sequence)
            vehicle = self.db.get(Vehicle, route.vehicle_id) if route.vehicle_id else None

            if vehicle and len(stops) >= 2:
                # Use network-free haversine estimates (this runs for every trip)
                from math import radians, sin, cos, sqrt, atan2

                total_distance = 0.0
                total_duration = 0.0

                geocoded = [s for s in stops if s.latitude and s.longitude]
                for prev, stop in zip(geocoded, geocoded[1:]):
                    R = 6371.0
                    lat1, lon1 = radians(prev.latitude), radians(prev.longitude)
                    lat2, lon2 = radians(stop.latitude), radians(stop.longitude)
                    dlat = lat2 - lat1
                    dlon = lon2 - lon1
                    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
                    c = 2 * atan2(sqrt(a), sqrt(1-a))
                    dist_km = R * c
                    total_distance += dist_km
                    total_duration += (dist_km / 40.0) * 3600

                # Weighted cost
                total_cost += total_distance * 0.3 + (total_duration / 60) * 0.25

        return total_cost

    def close(self):
        self.db.close()


def run_simulation(csv_path: str, **kwargs) -> SimulationResult:
    """Convenience function to run simulation."""
    engine = SimulationEngine()
    try:
        return engine.run_from_csv(csv_path, **kwargs)
    finally:
        engine.close()


def run_comparison(csv_path: str) -> dict:
    """Convenience function to run greedy vs LNS comparison."""
    engine = SimulationEngine()
    try:
        return engine.run_greedy_vs_lns_comparison(csv_path)
    finally:
        engine.close()