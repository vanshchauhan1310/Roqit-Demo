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

from sqlalchemy import or_, func

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
    # Trips marked "unassigned" after an earlier resource shortage can still
    # carry a route_id once vehicles/drivers became available (the status flag
    # was never healed). For prediction purposes a routed trip IS active —
    # route-less "unassigned" trips stay excluded below by the route_id filter.

    "unassigned",
)


def _completed_pickup_count(db, route_pk) -> int:
    """Number of completed pickup stops on a route (= delivered trips)."""
    return (
        db.query(Trip.trip_id)
        .join(RouteStop, RouteStop.trip_id == Trip.trip_id)
        .filter(
            RouteStop.route_id == route_pk,
            RouteStop.stop_type == "pickup",
            Trip.status == COMPLETED_TRIP_STATUS,
        )
        .count()
    )


def _crossed_prediction_threshold(before: int, after: int) -> bool:
    """True when the completed-trip count moved past a multiple of N.

    Comparing floor(before/N) < floor(after/N) means a sweep that completes
    2+ trips at once (e.g. count 2 -> 4) still fires exactly once, and a
    count that lands short of the next multiple never fires.
    """
    n = PREDICTION_TRIGGER_EVERY_N
    return (before // n) < (after // n)


def _repredict_route_trips(route_pk=None, exclude_ids: set | None = None) -> tuple[int, int]:
    """Re-run the delay prediction for trips with assigned resources.

    Fleet-wide by default: when called with no route_pk (the milestone trigger
    path) it re-predicts EVERY active trip across ALL routes - completions on
    any route shift global history features (driver/vehicle/route delay rates),
    and live weather changes, so every outstanding prediction goes stale, not
    just the triggering route's. A specific route_pk scopes it to that route
    only (used by tests / targeted re-runs).

    Runs strictly AFTER the completion commit, on fresh sessions, so the ML
    round-trips (one per trip, plus a live weather fetch each) never hold the
    completion sweep's transaction open. A failure on one trip is logged and
    skipped - the next threshold crossing will retry it.

    Trips that already have a prediction stored within the last
    PREDICTION_STALENESS_MINUTES are skipped so the fleet sweep doesn't
    re-predict every trip every milestone fire (which could be dozens of
    ML calls per trigger). This keeps the fleet endpoint responsive while
    still refreshing stale predictions on each milestone.
    """
    import asyncio
    from datetime import timedelta, timezone
    from app.services.delay_prediction_service import (
        MissingFeatureDataError,
        predict_delay_for_trip,
    )
    from app.models.delay_prediction import DelayPrediction as _DelayPrediction

    db = SessionLocal()
    try:
        # Subquery: the most-recent prediction timestamp per trip.
        latest_pred = (
            db.query(
                _DelayPrediction.trip_id,
                func.max(_DelayPrediction.predicted_at).label("last_pred"),
            )
            .group_by(_DelayPrediction.trip_id)
            .subquery()
        )

        cutoff = datetime.now(timezone.utc) - timedelta(minutes=PREDICTION_STALENESS_MINUTES)

        query = (
            db.query(Trip.trip_id)
            .filter(
                Trip.vehicle_id.isnot(None),
                Trip.driver_id.isnot(None),
            )
            .outerjoin(latest_pred, Trip.trip_id == latest_pred.c.trip_id)
            .filter(or_(latest_pred.c.trip_id.is_(None), latest_pred.c.last_pred < cutoff))
            .order_by(Trip.assigned_at.desc().nullslast())
        )

        if route_pk is not None:
            query = query.join(RouteStop, RouteStop.trip_id == Trip.trip_id).filter(
                RouteStop.route_id == route_pk,
                RouteStop.stop_type == "pickup",
            )
        if exclude_ids:
            query = query.filter(~Trip.trip_id.in_(exclude_ids))
        remaining_ids = [
            row[0] for row in query.limit(PREDICTION_MAX_TRIPS_PER_RUN).all()
        ]
        if exclude_ids:
            exclude_ids.update(remaining_ids)
    finally:
        db.close()

    predicted = failed = 0
    for trip_id in remaining_ids:
        session = SessionLocal()
        try:
            trip = session.get(Trip, trip_id)
            if trip is None or trip.vehicle_id is None or trip.driver_id is None:
                continue
            asyncio.run(predict_delay_for_trip(session, trip))
            predicted += 1
        except MissingFeatureDataError as exc:
            failed += 1
            print(f"[PREDICT] {trip_id}: skipped ({exc})")
        except Exception as exc:  # pragma: no cover - defensive
            failed += 1
            print(f"[PREDICT] {trip_id}: prediction failed ({exc})")
        finally:
            session.close()

    print(
        f"[PREDICT] {PREDICTION_TRIGGER_EVERY_N}th trip milestone reached "
        f"- fleet-wide re-prediction of {predicted} active trip(s)"
        + (f", {failed} skipped/failed" if failed else "")
    )
    return predicted, failed


# After every Nth completed pickup on a route, re-run the delay prediction for
# the route's remaining (not-yet-delivered) trips. Completions change what the
# model sees: route/driver/vehicle delay history grows, cargo is released and
# the route is re-sequenced, and live weather is re-fetched - so a prediction
# made at assignment time goes stale. Re-predicting on this cadence keeps the
# dispatcher's risk badges aligned with the route's actual progress.
PREDICTION_TRIGGER_EVERY_N = 3

# Safety cap: never re-predict more than this many trips per trigger (one ML
# call per trip, plus a live weather fetch each - the cap bounds a single
# sweep's ML load). Since the trigger re-predicts fleet-wide, this covers all
# routes' active trips, ordered most-recently-assigned first via the query.
PREDICTION_MAX_TRIPS_PER_RUN = 50

# Skip trips whose last prediction is newer than this — avoids re-predicting
# the same trips on every milestone fire (the 3-trip trigger fires fleet-wide,
# and with a small demo fleet the same 50 trips would be hit every cycle).
# 5 minutes matches the frontend's useQuery staleTime so stale predictions
# are refreshed on each milestone rather than duplicated.
PREDICTION_STALENESS_MINUTES = 5


def _trigger_predictions_if_crossed(route_pks, before_counts) -> None:
    """Re-run delay predictions when any route just crossed an N-completion
    milestone. Re-prediction is FLEET-WIDE (all routes' active trips): history
    features are global aggregates, so a completion anywhere shifts what the
    model sees everywhere. Runs after the sweep commit, on fresh sessions; an
    error is logged and never breaks the sweep."""
    check_db = SessionLocal()
    crossed = False
    try:
        for pk in route_pks:
            after = _completed_pickup_count(check_db, pk)
            if _crossed_prediction_threshold(before_counts.get(pk, 0), after):
                crossed = True
                break
    finally:
        check_db.close()
    if crossed:
        try:
            _repredict_route_trips()
        except Exception as exc:  # pragma: no cover - defensive
            print(f"[PREDICT] fleet-wide trigger failed ({exc})")


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

        # Normalise Trip.route_id (String) to Route.route_id (UUID), and record
        # each route's completed-trip count BEFORE this sweep's completions -
        # the prediction trigger fires when a multiple-of-N boundary is crossed.
        route_pks = set()
        for t in trips:
            try:
                route_pks.add(uuid.UUID(str(t.route_id)))
            except (ValueError, TypeError):
                route_pks.add(t.route_id)
        before_counts = {pk: _completed_pickup_count(db, pk) for pk in route_pks}

        now = datetime.now(timezone.utc)
        for trip in trips:
            trip.status = COMPLETED_TRIP_STATUS
            if trip.actual_delivery_time is None:
                trip.actual_delivery_time = now
            db.add(trip)

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

        # Delay-prediction refresh: every Nth completed pickup on a route
        # re-predicts its remaining trips with updated history + live weather.
        _trigger_predictions_if_crossed(route_pks, before_counts)
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
