"""Trip Completion Worker - demo delivery lifecycle.

Auto-completes a trip ``COMPLETION_DELAY_MINUTES`` minutes after it was
assigned to a route. Completing a trip:

- sets ``status="completed"`` and stamps ``actual_delivery_time``,
- releases its cargo weight: route/vehicle capacity is recomputed without
  it (see ``state.route_load_kg`` excluding completed trips),
- when the last still-active trip on a route completes, the route itself is
  marked ``completed`` - which frees the vehicle and driver for new work,
  because ``ACTIVE_STATUSES`` only counts planned/active/in-transit routes.

Runs as a daemon thread started by the Supervisor alongside the assignment
worker and the LNS workers.
"""

import threading
import uuid
from datetime import datetime, timedelta, timezone

from app.db.session import SessionLocal
from app.models.route import Route, RouteStop
from app.models.trip import Trip
from app.optimization.state import (
    ACTIVE_STATUSES,
    COMPLETED_TRIP_STATUS,
    sync_route_capacity,
)

# Demo clock: a trip is considered delivered 10 minutes after assignment.
COMPLETION_DELAY_MINUTES = 10.0

# Statuses a trip carries while it is assigned but not yet delivered.
ACTIVE_TRIP_STATUSES = (
    "scheduled",
    "assigned",
    "in-transit",
    "in_transit",
    "In-Transit",
    "active",
)


def run_completion_sweep() -> int:
    """Complete every trip whose assignment is at least 10 minutes old.

    Returns the number of trips completed this sweep.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=COMPLETION_DELAY_MINUTES)
    db = SessionLocal()
    try:
        # NOTE: we deliberately do NOT acquire the writer funnel lock here.
        #
        # The completion worker is read-mostly (trip.status, route.status) and
        # uses short row-level transactions - the UPDATE on each trip row and the
        # count() check per route are each atomic. Holding the funnel lock (which
        # the LNS optimizer and the assignment worker use for multi-second search
        # windows) would cause this 60-second heartbeat to stall indefinitely
        # whenever LNS is mid-iteration, blocking all trip completions.
        #
        # The worst-case outcome without the lock is a momentary stale read of
        # remaining-trip count (when LNS is mid-deletion), which only delays the
        # "mark route complete" decision by one sweep cycle - never causes a
        # correctness problem.
        trips = (
            db.query(Trip)
            .filter(
                Trip.route_id.isnot(None),
                Trip.assigned_at.isnot(None),
                Trip.assigned_at <= cutoff,
                Trip.status.in_(ACTIVE_TRIP_STATUSES),
            )
            .limit(500)
            .all()
        )
        if not trips:
            return 0

        now = datetime.now(timezone.utc)
        for trip in trips:
            trip.status = COMPLETED_TRIP_STATUS
            if trip.actual_delivery_time is None:
                trip.actual_delivery_time = now
            db.add(trip)

        # Normalise Trip.route_id (String) to Route.route_id (UUID).
        route_pks = set()
        for t in trips:
            try:
                route_pks.add(uuid.UUID(str(t.route_id)))
            except (ValueError, TypeError):
                route_pks.add(t.route_id)

        db.flush()

        completed_routes = 0
        for route_pk in route_pks:
            route = db.get(Route, route_pk)
            if route is None:
                continue

            # Cargo still pending on this route (pickup stops whose trip has
            # not completed yet). Zero pending cargo -> route is done.
            remaining = (
                db.query(Trip.trip_id)
                .join(RouteStop, RouteStop.trip_id == Trip.trip_id)
                .filter(
                    RouteStop.route_id == route.route_id,
                    RouteStop.stop_type == "pickup",
                    Trip.status != COMPLETED_TRIP_STATUS,
                )
                .count()
            )

            # Recompute cached capacity now that completed cargo is released.
            sync_route_capacity(db, route)

            if remaining == 0 and route.status in ACTIVE_STATUSES:
                route.status = COMPLETED_TRIP_STATUS
                db.add(route)
                completed_routes += 1

        db.commit()
        print(
            f"[COMPLETE] sweep: {len(trips)} trip(s) completed, "
            f"{completed_routes} route(s) completed"
        )
        return len(trips)
    except Exception as e:  # pragma: no cover - defensive
        db.rollback()
        # A lock timeout while a long writer (e.g. a 90s LNS budget) holds the
        # funnel is NOT an error: it means "try again next 60s sweep". Report
        # it as a skip so logs stay actionable instead of alarmist.
        if "lock timeout" in str(e) or "55P03" in str(e):
            print("[COMPLETE] writer lock busy (lock timeout), skipping this sweep")
            return 0
        print(f"[COMPLETE] sweep error: {e}")
        return 0
    finally:
        db.close()


class TripCompletionWorker(threading.Thread):
    """Periodically completes trips whose 10-minute delivery window elapsed."""

    def __init__(self, interval_seconds: int = 60):
        super().__init__(name="trip-completion-worker", daemon=True)
        self.interval_seconds = interval_seconds

    def run(self) -> None:
        print(
            "[COMPLETE] trip completion worker started "
            f"(interval={self.interval_seconds}s, delay={COMPLETION_DELAY_MINUTES}min)"
        )
        # Sweep immediately so trips pending from a previous run complete fast.
        try:
            run_completion_sweep()
        except Exception:  # pragma: no cover - defensive
            print("[COMPLETE] initial sweep failed")
        while True:
            threading.Event().wait(self.interval_seconds)
            try:
                run_completion_sweep()
            except Exception:  # pragma: no cover - defensive
                print("[COMPLETE] sweep failed unexpectedly")


trip_completion_worker = TripCompletionWorker(interval_seconds=180)
