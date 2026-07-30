import math

import httpx
from fastapi import HTTPException

from app.core.config import settings
from app.schemas.optimize import OptimizeRouteResponse, OptimizeStopInput

# Above this many stops, exact Held-Karp (O(n^2 * 2^n)) gets too slow/memory-hungry —
# fall back to a nearest-neighbor + 2-opt heuristic instead.
EXACT_SOLVER_MAX_STOPS = 12


async def _fetch_matrices(stops: list[OptimizeStopInput]) -> tuple[list[list[float]], list[list[float]]]:
    coords = ";".join(f"{s.longitude},{s.latitude}" for s in stops)
    url = f"{settings.OSRM_BASE_URL}/table/v1/driving/{coords}?annotations=duration,distance"

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(url)

    if response.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Routing provider returned {response.status_code}")

    data = response.json()
    durations = data.get("durations")
    distances = data.get("distances")
    if not durations or not distances:
        raise HTTPException(status_code=502, detail="Routing provider returned no matrix")

    return durations, distances


def _held_karp_open_path(cost: list[list[float]]) -> list[int]:
    """Exact shortest Hamiltonian path starting at node 0 (no return to start)."""
    n = len(cost)
    if n <= 2:
        return list(range(n))

    size = 1 << n
    dp = [[math.inf] * n for _ in range(size)]
    parent = [[-1] * n for _ in range(size)]
    dp[1][0] = 0.0  # mask={0}, currently at node 0, cost 0

    for mask in range(size):
        if not (mask & 1):  # every valid state includes the fixed start node
            continue
        for j in range(n):
            if not (mask & (1 << j)) or dp[mask][j] == math.inf:
                continue
            base_cost = dp[mask][j]
            for k in range(n):
                if mask & (1 << k):
                    continue
                new_mask = mask | (1 << k)
                new_cost = base_cost + cost[j][k]
                if new_cost < dp[new_mask][k]:
                    dp[new_mask][k] = new_cost
                    parent[new_mask][k] = j

    full_mask = size - 1
    best_end = min(range(n), key=lambda j: dp[full_mask][j])

    order: list[int] = []
    mask, node = full_mask, best_end
    while node != -1:
        order.append(node)
        prev = parent[mask][node]
        mask ^= 1 << node
        node = prev
    order.reverse()
    return order


def _nearest_neighbor(cost: list[list[float]]) -> list[int]:
    n = len(cost)
    visited = [False] * n
    visited[0] = True
    order = [0]
    for _ in range(n - 1):
        last = order[-1]
        nxt = min((j for j in range(n) if not visited[j]), key=lambda j: cost[last][j])
        visited[nxt] = True
        order.append(nxt)
    return order


def _two_opt(order: list[int], cost: list[list[float]]) -> list[int]:
    """Local-search cleanup for the heuristic path; node 0 (index 0 in `order`) stays fixed."""
    n = len(order)
    improved = True
    while improved:
        improved = False
        for i in range(1, n - 1):
            for j in range(i + 1, n):
                a, b = order[i - 1], order[i]
                c = order[j]
                d = order[j + 1] if j + 1 < n else None
                before = cost[a][b] + (cost[c][d] if d is not None else 0)
                after = cost[a][c] + (cost[b][d] if d is not None else 0)
                if after < before - 1e-9:
                    order[i : j + 1] = list(reversed(order[i : j + 1]))
                    improved = True
    return order


def _solve_order(cost: list[list[float]]) -> list[int]:
    n = len(cost)
    if n <= EXACT_SOLVER_MAX_STOPS:
        return _held_karp_open_path(cost)
    return _two_opt(_nearest_neighbor(cost), cost)


async def optimize_route(stops: list[OptimizeStopInput]) -> OptimizeRouteResponse:
    if len(stops) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 stops to optimize")

    durations, distances = await _fetch_matrices(stops)
    order = _solve_order(durations)

    total_duration = sum(durations[order[i]][order[i + 1]] for i in range(len(order) - 1))
    total_distance = sum(distances[order[i]][order[i + 1]] for i in range(len(order) - 1))

    return OptimizeRouteResponse(
        order=[stops[i].key for i in order],
        total_duration_seconds=total_duration,
        total_distance_meters=total_distance,
    )
