"""LNS Worker - runs periodic Large Neighborhood Search optimization."""

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.route import Route
from app.models.trip import Trip
from app.optimization.lns.optimizer import LNSOptimizer, LNSDestroyStrategy, LNSRepairStrategy
from app.optimization.audit.logger import audit_logger
from app.infrastructure.queue import Queue, QueueJob, get_queue
from app.core.config import settings


class LNSWorker:
    """Worker that runs periodic LNS optimization."""

    def __init__(self):
        self.queue = get_queue()
        self.optimizer = LNSOptimizer(
            destroy_strategy=LNSDestroyStrategy.RANDOM,
            repair_strategy=LNSRepairStrategy.REGRET_2,
            destroy_percentage=settings.LNS_DESTROY_PERCENTAGE,
        )

    def handle_job(self, job: QueueJob) -> bool:
        """Handle an LNS optimization job."""
        print("Running periodic LNS optimization...")

        db = SessionLocal()
        try:
            # Get active routes to optimize
            routes = db.query(Route).filter(
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
            db.close()

    def run_once(self) -> None:
        """Run LNS optimization once (for manual trigger)."""
        db = SessionLocal()
        try:
            routes = db.query(Route).filter(
                Route.status.in_(["planned", "active", "in-transit"])
            ).all()

            if len(routes) < 2:
                print("Not enough routes for LNS optimization")
                return

            result = self.optimizer.optimize(db, routes)
            print(f"LNS result: {result}")

        finally:
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