"""Destroy operators for LNS."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.route import Route, RouteStop
from app.models.trip import Trip
from app.optimization.state import sync_route_capacity


@dataclass
class DestroyResult:
    """Result of a destroy operation."""
    removed_trips: list[Trip]
    modified_routes: list[Route]
    removed_stop_ids: list[UUID]


class DestroyOperator(ABC):
    """Base class for destroy operators."""

    @abstractmethod
    def destroy(
        self,
        db: Session,
        routes: list[Route],
        destroy_percentage: float = 0.2,
    ) -> DestroyResult:
        """Remove trips from routes.

        Args:
            db: Database session
            routes: Routes to destroy
            destroy_percentage: Fraction of trips to remove (0.1-0.3)

        Returns:
            DestroyResult with removed trips and modified routes
        """
        pass


class RandomDestroy(DestroyOperator):
    """Randomly removes trips from routes."""

    def destroy(
        self,
        db: Session,
        routes: list[Route],
        destroy_percentage: float = 0.2,
    ) -> DestroyResult:
        import random

        all_removable_trips = []

        for route in routes:
            # Get trips that can be removed (not frozen)
            frozen_until = route.frozen_until_sequence or 0
            removable_stops = [
                s for s in route.stops
                if s.trip_id and s.sequence > frozen_until and s.stop_type == "pickup"
            ]

            # Group by trip_id
            trip_stops = {}
            for stop in removable_stops:
                trip_stops.setdefault(stop.trip_id, []).append(stop)

            for trip_id, stops in trip_stops.items():
                # Need both pickup and delivery
                pickup = next((s for s in stops if s.stop_type == "pickup"), None)
                delivery = next((s for s in route.stops if s.trip_id == trip_id and s.stop_type == "delivery"), None)
                if pickup and delivery:
                    trip = db.get(Trip, trip_id)
                    if trip:
                        all_removable_trips.append((route, trip, pickup, delivery))

        # Randomly select trips to remove
        num_to_remove = max(1, int(len(all_removable_trips) * destroy_percentage))
        selected = random.sample(all_removable_trips, min(num_to_remove, len(all_removable_trips)))

        removed_trips = []
        modified_routes = set()
        removed_stop_ids = []

        for route, trip, pickup, delivery in selected:
            # Remove stops from route
            db.delete(pickup)
            db.delete(delivery)
            removed_stop_ids.extend([pickup.stop_id, delivery.stop_id])

            # Clear trip assignment
            trip.route_id = None
            trip.assigned_at = None
            db.add(trip)

            removed_trips.append(trip)
            modified_routes.add(route)

        # Flush pending deletes so the deleted RouteStop rows are removed from
        # the identity map; otherwise they linger in route.stops collections
        # and crash subsequent access with "Instance has been deleted".
        db.flush()

        # Refresh routes and synchronise cached capacity fields from the
        # surviving stops, so destroy never leaves stale used/remaining
        # capacity (phantom utilization) behind.
        # Expire the stops relationship so SQLAlchemy reloads it from the
        # database (deleted stops are gone; survivors only).
        for route in modified_routes:
            db.refresh(route)
            db.expire(route, ['stops'])
            sync_route_capacity(db, route)

        return DestroyResult(
            removed_trips=removed_trips,
            modified_routes=list(modified_routes),
            removed_stop_ids=removed_stop_ids,
        )


class WorstCostDestroy(DestroyOperator):
    """Removes trips with highest marginal cost."""

    def __init__(self, cost_function=None):
        self.cost_function = cost_function

    def destroy(
        self,
        db: Session,
        routes: list[Route],
        destroy_percentage: float = 0.2,
    ) -> DestroyResult:
        # TODO: Calculate marginal cost for each trip and remove highest
        # For now, fall back to random
        from app.optimization.lns.destroy import RandomDestroy
        return RandomDestroy().destroy(db, routes, destroy_percentage)


class RelatedDestroy(DestroyOperator):
    """Removes geographically related trips."""

    def destroy(
        self,
        db: Session,
        routes: list[Route],
        destroy_percentage: float = 0.2,
    ) -> DestroyResult:
        # TODO: Cluster trips geographically and remove entire clusters
        # For now, fall back to random
        from app.optimization.lns.destroy import RandomDestroy
        return RandomDestroy().destroy(db, routes, destroy_percentage)


class RouteDestroy(DestroyOperator):
    """Removes all trips from selected routes."""

    def destroy(
        self,
        db: Session,
        routes: list[Route],
        destroy_percentage: float = 0.2,
    ) -> DestroyResult:
        import random

        # Select routes to destroy
        num_routes = max(1, int(len(routes) * destroy_percentage))
        selected_routes = random.sample(routes, min(num_routes, len(routes)))

        removed_trips = []
        modified_routes = []
        removed_stop_ids = []

        for route in selected_routes:
            frozen_until = route.frozen_until_sequence or 0
            removable_stops = [
                s for s in route.stops
                if s.trip_id and s.sequence > frozen_until
            ]

            # Group by trip
            trip_stops = {}
            for stop in removable_stops:
                trip_stops.setdefault(stop.trip_id, []).append(stop)

            for trip_id, stops in trip_stops.items():
                pickup = next((s for s in stops if s.stop_type == "pickup"), None)
                delivery = next((s for s in stops if s.stop_type == "delivery"), None)
                if pickup and delivery:
                    trip = db.get(Trip, trip_id)
                    if trip:
                        db.delete(pickup)
                        db.delete(delivery)
                        removed_stop_ids.extend([pickup.stop_id, delivery.stop_id])

                        trip.route_id = None
                        trip.assigned_at = None
                        db.add(trip)

                        removed_trips.append(trip)

            modified_routes.append(route)

        # NOTE: intentionally NO db.commit() here.  Same rationale as in
        # RandomDestroy: the destroy phase only stages changes in the current
        # transaction; the LNS optimizer commits/rolls back atomically per
        # iteration, so a failed run can never strand trips un-assigned.

        for route in modified_routes:
            db.refresh(route)
            sync_route_capacity(db, route)

        return DestroyResult(
            removed_trips=removed_trips,
            modified_routes=modified_routes,
            removed_stop_ids=removed_stop_ids,
        )


class DelayDestroy(DestroyOperator):
    """Removes trips contributing most to delay."""

    def destroy(
        self,
        db: Session,
        routes: list[Route],
        destroy_percentage: float = 0.2,
    ) -> DestroyResult:
        # TODO: Analyze delay contribution and remove highest
        # For now, fall back to random
        from app.optimization.lns.destroy import RandomDestroy
        return RandomDestroy().destroy(db, routes, destroy_percentage)


# Instances
random_destroy = RandomDestroy()
worst_cost_destroy = WorstCostDestroy()
related_destroy = RelatedDestroy()
route_destroy = RouteDestroy()
delay_destroy = DelayDestroy()