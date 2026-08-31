"""Queue infrastructure using Redis."""

import json
import threading
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional, Callable, Any
from uuid import UUID

import redis


@dataclass
class QueueJob:
    """A job in the queue."""
    job_id: str
    queue_name: str
    payload: dict
    attempt: int = 1
    created_at: str = ""
    scheduled_at: Optional[str] = None

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.utcnow().isoformat()
        if not self.job_id:
            self.job_id = str(uuid.uuid4())


class Queue:
    """Redis-based queue with basic job processing."""

    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        self.redis = redis.from_url(
            redis_url,
            decode_responses=True,
            socket_keepalive=True,
            health_check_interval=30,
        )
        self._running = False

    def enqueue(self, queue_name: str, payload: dict, delay_seconds: int = 0) -> str:
        """Add a job to the queue."""
        job = QueueJob(
            job_id=str(uuid.uuid4()),
            queue_name=queue_name,
            payload=payload,
        )
        job_data = json.dumps(asdict(job))

        if delay_seconds > 0:
            # Use sorted set for delayed jobs
            score = datetime.utcnow().timestamp() + delay_seconds
            self.redis.zadd(f"queue:{queue_name}:delayed", {job_data: score})
        else:
            self.redis.lpush(f"queue:{queue_name}", job_data)

        return job.job_id

    def dequeue(self, queue_name: str, timeout: int = 5) -> Optional[QueueJob]:
        """Get a job from the queue (blocking)."""
        # First check delayed jobs that are ready
        self._move_ready_delayed_jobs(queue_name)

        # Blocking pop
        result = self.redis.brpop(f"queue:{queue_name}", timeout=timeout)
        if result:
            _, job_data = result
            job_dict = json.loads(job_data)
            return QueueJob(**job_dict)
        return None

    def _move_ready_delayed_jobs(self, queue_name: str) -> None:
        """Move ready delayed jobs to main queue."""
        now = datetime.utcnow().timestamp()
        ready_jobs = self.redis.zrangebyscore(
            f"queue:{queue_name}:delayed", 0, now
        )
        for job_data in ready_jobs:
            self.redis.lpush(f"queue:{queue_name}", job_data)
            self.redis.zrem(f"queue:{queue_name}:delayed", job_data)

    def requeue(self, queue_name: str, job: QueueJob, delay_seconds: int = 0) -> str:
        """Requeue a job (e.g., after failure)."""
        job.attempt += 1
        return self.enqueue(queue_name, job.payload, delay_seconds)

    def get_queue_length(self, queue_name: str) -> int:
        """Get number of pending jobs."""
        main = self.redis.llen(f"queue:{queue_name}")
        delayed = self.redis.zcard(f"queue:{queue_name}:delayed")
        return main + delayed


class Worker:
    """Base worker class for processing queue jobs."""

    def __init__(
        self,
        queue: Queue,
        queue_name: str,
        handler: Callable[[QueueJob], bool],
        max_retries: int = 3,
        retry_delay: int = 60,
    ):
        self.queue = queue
        self.queue_name = queue_name
        self.handler = handler
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._running = False

    def start(self) -> None:
        """Start processing jobs."""
        self._running = True
        while self._running:
            try:
                job = self.queue.dequeue(self.queue_name, timeout=5)
                if job:
                    self._process_job(job)
            except redis.exceptions.TimeoutError:
                # BRPOP expiry can surface as a socket timeout on stale
                # connections; this is an empty-queue condition, not an error.
                continue
            except redis.exceptions.ConnectionError as e:
                print(f"Worker connection error (will retry): {e}")
                threading.Event().wait(1)
            except Exception as e:
                print(f"Worker error: {e}")

    def stop(self) -> None:
        """Stop the worker."""
        self._running = False

    def _process_job(self, job: QueueJob) -> None:
        """Process a single job with retry logic."""
        try:
            success = self.handler(job)
            if not success and job.attempt < self.max_retries:
                # Requeue with delay
                delay = self.retry_delay * job.attempt
                self.queue.requeue(self.queue_name, job, delay)
                print(f"Job {job.job_id} failed, requeued (attempt {job.attempt + 1})")
            elif not success:
                print(f"Job {job.job_id} failed permanently after {job.attempt} attempts")
        except Exception as e:
            print(f"Job {job.job_id} exception: {e}")
            if job.attempt < self.max_retries:
                delay = self.retry_delay * job.attempt
                self.queue.requeue(self.queue_name, job, delay)


# Global queue instance
queue = None

def get_queue() -> Queue:
    """Get or create the global queue instance."""
    global queue
    if queue is None:
        from app.core.config import settings
        queue = Queue(settings.REDIS_URL)
    return queue