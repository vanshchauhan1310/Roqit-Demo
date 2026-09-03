"""Distributed fleet write-lock (Redis).

Serialises the heavy plan-mutating workers (LNS optimiser, trip-assignment,
trip-completion sweep) so they never hold overlapping row locks on
``routes`` / ``route_stops`` / ``trips`` at the same time — overlapping
row-lock acquisitions in different orders were producing recurring Postgres
deadlocks that aborted LNS runs and assignment jobs.

Usage:
    with fleet_write_lock():
        ...mutate routes/trips...

If Redis is down or the lock cannot be acquired within ``wait_seconds``,
execution proceeds UNLOCKED (logged) — the per-transaction deadlock retry
in the LNS optimiser remains the safety net, so a degraded lock never
becomes a stalled pipeline.
"""

import contextlib
import time
import uuid
from typing import Iterator

from app.infrastructure.queue import get_queue

LOCK_KEY = "lock:fleet-plan-write"

# LNS budget is LNS_ITERATION_BUDGET_SECONDS (default 90s); give the lock a
# TTL with comfortable headroom so a crashed holder can't wedge the fleet.
DEFAULT_TTL_MS = 180_000
DEFAULT_WAIT_S = 150.0
_POLL_S = 0.25

_RELEASE_LUA = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then "
    "return redis.call('del', KEYS[1]) else return 0 end"
)


@contextlib.contextmanager
def fleet_write_lock(
    wait_seconds: float = DEFAULT_WAIT_S,
    ttl_ms: int = DEFAULT_TTL_MS,
) -> Iterator[bool]:
    """Hold the fleet-plan write lock; yields True if it was acquired."""
    token = uuid.uuid4().hex
    acquired = False
    try:
        redis = get_queue().redis
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            try:
                if redis.set(LOCK_KEY, token, nx=True, px=ttl_ms):
                    acquired = True
                    break
            except Exception:
                # Redis unreachable — don't stall the demo, run unlocked.
                break
            time.sleep(_POLL_S)
        if not acquired:
            print("[LOCK] fleet write-lock not acquired in time; proceeding unlocked")
        yield acquired
    finally:
        if acquired:
            try:
                get_queue().redis.eval(_RELEASE_LUA, 1, LOCK_KEY, token)
            except Exception:  # pragma: no cover - defensive
                pass
