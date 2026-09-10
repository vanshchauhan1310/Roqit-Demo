"""LNS Worker - runs Large Neighborhood Search optimization (MANUAL TRIGGER ONLY)."""

import threading
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session, selectinload

from app.db.session import SessionLocal
from app.models.route import Route
from app.models.trip import Trip
from app.optimization.lns.optimizer import LNSOptimizer, LNSDestroyStrategy, LNSRepairStrategy
from app.optimization.audit.logger import audit_logger
from app.infrastructure.queue import Queue, QueueJob, get_queue
from app.core.config import settings
from app.workers.trip_assignment_worker import assignment_paused, sweep_unassigned_trips


class LNSWorker:
    """Worker that runs LNS optimization (manual trigger only)."""

    # Process-level guard: the queue may deliver a new LNS job while a
    # previous run is still executing (manual trigger).
    # Concurrent runs don't corrupt anything (the writer funnel advisory
    # lock serializes them) but each queued contender burns a 30s
    # lock_timeout + retry cycle for nothing. Skipping is cheaper and keeps
    # the funnel free for the trip-assignment / trip-completion workers.
    _run_lock = threading.Lock()

    def __init__(self):
        self.queue = get_queue()
        self.optimizer = LNSOptimizer(
            destroy_strategy=LNSDestroyStrategy.RANDOM,
            repair_strategy=LNSRepairStrategy.REGRET_2,
            destroy_percentage=settings.LNS_DESTROY_PERCENTAGE,
        )

    def handle_job(self, job: QueueJob) -> bool:
        """Handle an LNS optimization job."""
        if not LNSWorker._run_lock.acquire(blocking=False):
            print("LNS job skipped: another optimization run is already in progress")
            return True

        try:
            return self._run_optimization(job)
        finally:
            LNSWorker._run_lock.release()

    def _run_optimization(self, job: QueueJob) -> bool:
        """Run the LNS optimization (caller holds the run lock)."""
        print("Running LNS optimization (manual trigger)...")

        db = SessionLocal()
        # Pause greedy assignment + unassigned sweeps for the duration of the
        # run: the assignment worker holds the writer-funnel advisory lock for
        # the whole (slow) candidate search, and with the sweeper re-feeding
        # jobs the funnel is never free - every LNS iteration timed out
        # acquiring it and runs finished with 0 iterations. The in-flight job
        # (if any) finishes first; its commit releases the funnel for LNS.
        assignment_paused.set()
        try:
            # Get active routes to optimize (eager-load stops: avoids N+1 lazy-load per feasibility check)
            routes = db.query(Route).options(selectinload(Route.stops)).filter(
                Route.status.in_(["planned", "active", "in-transit"])
            ).all()

            if len(routes) < 2:
                print("Not enough routes for LNS optimization")
                return True

            # Run LNS optimization
            run_id = UUID(job.payload.get("run_id")) if job.payload.get("run_id") else None
            result = self.optimizer.optimize(db, routes, run_id)

            if result.success:
                print(f"LNS optimization completed: improvement={result.improvement:.2f}")
            else:
                print(f"LNS optimization rejected: {result.error_message}")

            return True

        except Exception as e:
            print(f"LNS optimization error: {e}")
            return False
        finally:
            # Un-pause first so the immediate catch-up sweep is allowed through.
            assignment_paused.clear()
            # Immediately re-drain whatever was skipped while paused instead of
            # waiting up to 60s for the sweeper's next tick.
            try:
                deferred = sweep_unassigned_trips(batch=25)
                if deferred:
                    print(f"LNS run finished: re-enqueued {deferred} deferred trip(s)")
            except Exception:
                print("LNS run finished: post-run sweep failed (sweeper will retry)")
            db.close()

    def run_once(self) -> None:
        """Run LNS optimization once (for manual trigger)."""
        db = SessionLocal()
        assignment_paused.set()
        try:
            routes = db.query(Route).options(selectinload(Route.stops)).filter(
                Route.status.in_(["planned", "active", "in-transit"])
            ).all()

            if len(routes) < 2:
                print("Not enough routes for LNS optimization")
                return

            result = self.optimizer.optimize(db, routes)
            print(f"LNS result: {result}")

        finally:
            assignment_paused.clear()
            db.close()


def create_lns_job(run_id: Optional[str] = None) -> str:
    """Create an LNS optimization job in the queue."""
    queue = get_queue()
    payload = {}
    if run_id:
        payload["run_id"] = run_id
    return queue.enqueue("lns-optimization", payload)


# Worker instance
lns_worker = LNSWorker()