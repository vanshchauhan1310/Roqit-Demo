"""Worker supervisor.

Owns the *lifespan* of the asynchronous background work the dynamic
optimization engine needs:

- a queue consumer for ``trip-assignment`` jobs (greedy best insertion), and
- a queue consumer for ``lns-optimization`` jobs (periodic/triggered LNS), plus
- a scheduler that enqueues an LNS job every ``LNS_INTERVAL_MINUTES``.

Started/stopped by the FastAPI lifespan hook so the API process itself runs the
workers (a single-producer/single-consumer design appropriate for this scale).
Each thread is a daemon so a process shutdown does not hang.
"""

import logging
import threading

from app.core.config import settings
from app.infrastructure.queue import Queue, Worker, get_queue
from app.workers.lns_worker import create_lns_job, lns_worker
from app.workers.trip_assignment_worker import trip_assignment_worker, sweep_unassigned_trips

logger = logging.getLogger(__name__)


class LNSScheduler(threading.Thread):
    """Enqueues an LNS optimization job every interval."""

    def __init__(self, interval_minutes: int, queue: Queue):
        super().__init__(name="lns-scheduler", daemon=True)
        self.interval_minutes = interval_minutes
        self.queue = queue

    def run(self) -> None:
        logger.info("LNS scheduler started (interval=%s min)", self.interval_minutes)
        while True:
            # Tick once immediately so LNS is cheap to smoke-test, then sleep.
            try:
                self._enqueue()
            except Exception:  # pragma: no cover - defensive
                logger.exception("LNS scheduler enqueue failed")
            threading.Event().wait(self.interval_minutes * 60)

    def _enqueue(self) -> None:
        create_lns_job()  # uses the global queue


class UnassignedSweeper(threading.Thread):
    """Periodically re-enqueues trips stuck unassigned so the backlog drains.

    Keeps the Live Ops "queue depth" honest: when no new trips are arriving
    and the worker is healthy, the queue returns to ~0 instead of growing
    forever from lost/old jobs.
    """

    def __init__(self, interval_seconds: int = 60, batch: int = 25):
        super().__init__(name="unassigned-sweeper", daemon=True)
        self.interval_seconds = interval_seconds
        self.batch = batch

    def run(self) -> None:
        logger.info("Unassigned sweeper started (interval=%s s)", self.interval_seconds)
        # Sweep immediately on startup to clear any accumulated backlog.
        try:
            sweep_unassigned_trips(batch=self.batch)
        except Exception:  # pragma: no cover - defensive
            logger.exception("Initial unassigned sweep failed")
        while True:
            threading.Event().wait(self.interval_seconds)
            try:
                sweep_unassigned_trips(batch=self.batch)
            except Exception:  # pragma: no cover - defensive
                logger.exception("Unassigned sweep failed")


class Supervisor:
    """Starts/stops the background worker threads."""

    def __init__(self) -> None:
        self._threads: list[threading.Thread] = []
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        queue = get_queue()

        trip_worker = Worker(
            queue,
            settings.TRIP_ASSIGNMENT_QUEUE,
            trip_assignment_worker.handle_job,
        )
        lns_consumer = Worker(
            queue,
            "lns-optimization",
            lns_worker.handle_job,
        )
        scheduler = LNSScheduler(settings.LNS_INTERVAL_MINUTES, queue)
        sweeper = UnassignedSweeper(interval_seconds=60, batch=25)

        self._threads = [
            threading.Thread(target=trip_worker.start, name="trip-assignment-worker", daemon=True),
            threading.Thread(target=lns_consumer.start, name="lns-worker", daemon=True),
            scheduler,
            sweeper,
        ]
        for thread in self._threads:
            thread.start()
        self._started = True
        logger.info("Optimization workers started: %s jobs are pending",
                    queue.get_queue_length(settings.TRIP_ASSIGNMENT_QUEUE))

    def stop(self) -> None:
        self._started = False
        logger.info("Optimization workers stopped")


supervisor = Supervisor()