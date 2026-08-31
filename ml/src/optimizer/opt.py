"""Exact-insertion pickup-delivery route solver.

"Exact" describes the insertion-cost evaluation: every candidate insertion
position considered here is scored by recomputing the real route cost from
the duration matrix, not approximated. This is NOT a certified globally
optimal solver (unlike the Held-Karp DP this module replaces, which was
exact-and-optimal for plain TSP up to ~12 stops) - it's a strong
constructive + Large Neighborhood Search (LNS) heuristic. hybrid_solver.py
treats this module's output as ground truth for training labels and for
exact feasibility verification, but "ground truth" here means "the best
answer this heuristic reliably finds", not "the provably optimal answer".

A "job" is one trip's pickup+delivery pair. Pairs are never split: LNS
destroy always removes both stops of a job together, and repair always
reinserts them together (see _destroy/_repair) - a vehicle can't drop
cargo it hasn't picked up.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Literal

Matrix = list[list[float]]

LATENESS_WEIGHT = 60.0


@dataclass
class Job:
    trip_id: str
    pickup_idx: int
    delivery_idx: int
    load_weight_kg: float = 0.0
    pickup_earliest: int | None = None
    pickup_latest: int | None = None
    delivery_earliest: int | None = None
    delivery_latest: int | None = None
    service_time_sec: int = 300


@dataclass
class SolveResult:
    route: list[int]
    total_duration_seconds: float
    total_distance_meters: float
    feasible: bool
    total_lateness_seconds: float = 0.0
    solver_used: Literal["exact", "hybrid"] = "exact"


def route_cost(route: list[int], duration_matrix: Matrix) -> float:
    return sum(duration_matrix[route[i]][route[i + 1]] for i in range(len(route) - 1))


def route_total_cost(
    route: list[int],
    duration_matrix: Matrix,
    jobs: list[Job],
    vehicle_capacity_kg: float | None,
    start_time: int = 0,
) -> float:
    """Total cost = travel duration + lateness penalty."""
    duration = route_cost(route, duration_matrix)
    lateness = route_is_feasible(route, jobs, vehicle_capacity_kg, duration_matrix, start_time)
    if lateness == float('inf'):
        return float('inf')
    return duration + lateness * LATENESS_WEIGHT


def route_distance(route: list[int], distance_matrix: Matrix) -> float:
    return sum(distance_matrix[route[i]][route[i + 1]] for i in range(len(route) - 1))


def _calculate_lateness(
    route: list[int],
    jobs: list[Job],
    duration_matrix: Matrix,
    start_time: int = 0,
) -> float:
    """Calculate total lateness in seconds for a route given time windows.
    Returns 0 if all windows met, positive seconds if late."""
    job_by_stop = {}
    for job in jobs:
        job_by_stop[job.pickup_idx] = job
        job_by_stop[job.delivery_idx] = job

    current_time = start_time
    total_lateness = 0.0

    for i, stop_idx in enumerate(route):
        job = job_by_stop.get(stop_idx)
        if job is None:
            continue

        is_pickup = stop_idx == job.pickup_idx
        earliest = job.pickup_earliest if is_pickup else job.delivery_earliest
        latest = job.pickup_latest if is_pickup else job.delivery_latest

        if earliest is not None and latest is not None:
            if current_time < earliest:
                current_time = earliest
            elif current_time > latest:
                total_lateness += current_time - latest

        current_time += job.service_time_sec
        if i + 1 < len(route):
            current_time += duration_matrix[stop_idx][route[i + 1]]

    return total_lateness


def route_is_feasible(
    route: list[int],
    jobs: list[Job],
    vehicle_capacity_kg: float | None,
    duration_matrix: Matrix | None = None,
    start_time: int = 0,
) -> float:
    """Check feasibility and return total lateness in seconds.
    Returns 0.0 if feasible with no lateness, positive if late, float('inf') if infeasible.
    
    Feasibility checks:
    - No duplicate stops
    - Pickup before delivery for each job
    - Vehicle capacity not exceeded
    - Time windows (soft constraint - lateness returned as penalty)"""
    if len(route) != len(set(route)):
        return float('inf')

    position = {stop: i for i, stop in enumerate(route)}
    for job in jobs:
        if job.pickup_idx not in position or job.delivery_idx not in position:
            return float('inf')
        if position[job.pickup_idx] >= position[job.delivery_idx]:
            return float('inf')

    if vehicle_capacity_kg is not None:
        for load in _load_at_positions(route, jobs):
            if load > vehicle_capacity_kg + 1e-9 or load < -1e-9:
                return float('inf')

    if duration_matrix is not None:
        return _calculate_lateness(route, jobs, duration_matrix, start_time)

    return 0.0


def insertion_delta(route: list[int], position: int, stop_idx: int, duration_matrix: Matrix) -> float:
    """Triangle-inequality detour cost of inserting stop_idx at `position`
    (0..len(route)) into `route`. Used only for quick candidate pre-filtering
    (e.g. by hybrid_solver's feature extraction) - best_pair_insertion itself
    scores candidates by exact full route-cost recomputation, not this delta,
    since a pickup+delivery pair inserted close together can interact in ways
    a naive delta sum over each stop in isolation would miss."""
    if not route:
        return 0.0
    if position == 0:
        return duration_matrix[stop_idx][route[0]]
    if position == len(route):
        return duration_matrix[route[-1]][stop_idx]
    prev_stop, next_stop = route[position - 1], route[position]
    return (
        duration_matrix[prev_stop][stop_idx]
        + duration_matrix[stop_idx][next_stop]
        - duration_matrix[prev_stop][next_stop]
    )


def insert_pair(route: list[int], job: Job, pickup_pos: int, delivery_pos: int) -> list[int]:
    """Pure function - returns a NEW list, `route` is untouched. pickup_pos
    and delivery_pos are both indices into the ORIGINAL `route` (before
    either stop is inserted), with 0 <= pickup_pos <= delivery_pos <= len(route)."""
    with_pickup = route[:pickup_pos] + [job.pickup_idx] + route[pickup_pos:]
    shifted_delivery_pos = delivery_pos + 1  # pickup insertion shifted everything from delivery_pos onward
    return with_pickup[:shifted_delivery_pos] + [job.delivery_idx] + with_pickup[shifted_delivery_pos:]


def _load_at_positions(route: list[int], jobs: list[Job]) -> list[float]:
    """Cumulative vehicle load immediately after visiting each stop in `route`."""
    delta: dict[int, float] = {}
    for job in jobs:
        delta[job.pickup_idx] = delta.get(job.pickup_idx, 0.0) + job.load_weight_kg
        delta[job.delivery_idx] = delta.get(job.delivery_idx, 0.0) - job.load_weight_kg

    loads = []
    running = 0.0
    for stop in route:
        running += delta.get(stop, 0.0)
        loads.append(running)
    return loads


def best_pair_insertion(
    route: list[int],
    job: Job,
    duration_matrix: Matrix,
    vehicle_capacity_kg: float | None,
    placed_jobs: list[Job],
    pickup_positions: list[int] | None = None,
    delivery_positions: list[int] | None = None,
    start_time: int = 0,
) -> tuple[int, int, float] | None:
    """Exhaustive search over every feasible (pickup_pos, delivery_pos) pair -
    O(n^2) candidate positions in len(route) by default. Pass
    pickup_positions/delivery_positions (each a list of original-route
    indices) to restrict the search to a pruned candidate set instead - used
    by hybrid_solver's spatially-pruned path. Returns (pickup_pos,
    delivery_pos, added_cost) for the cheapest FEASIBLE insertion found, or
    None if nothing in the searched candidate set is feasible."""
    n = len(route)
    base_cost = route_total_cost(route, duration_matrix, placed_jobs, vehicle_capacity_kg, start_time)
    pickup_candidates = pickup_positions if pickup_positions is not None else list(range(n + 1))

    best: tuple[int, int, float] | None = None
    for pickup_pos in pickup_candidates:
        if not (0 <= pickup_pos <= n):
            continue
        delivery_candidates = delivery_positions if delivery_positions is not None else list(range(n + 1))
        for delivery_pos in delivery_candidates:
            if not (pickup_pos <= delivery_pos <= n):
                continue
            candidate_route = insert_pair(route, job, pickup_pos, delivery_pos)
            candidate_cost = route_total_cost(
                candidate_route, duration_matrix, placed_jobs + [job], vehicle_capacity_kg, start_time
            )
            if candidate_cost == float('inf'):
                continue
            added_cost = candidate_cost - base_cost
            if best is None or added_cost < best[2]:
                best = (pickup_pos, delivery_pos, added_cost)
    return best


def construct_greedy(
    jobs: list[Job],
    duration_matrix: Matrix,
    vehicle_capacity_kg: float | None,
    start_time: int = 0,
) -> list[int]:
    """Builds a route from empty by inserting jobs one at a time, in input
    order, at each job's cheapest feasible position (cheapest insertion
    heuristic)."""
    route: list[int] = []
    placed: list[Job] = []
    for job in jobs:
        if not route:
            route = [job.pickup_idx, job.delivery_idx]
        else:
            result = best_pair_insertion(route, job, duration_matrix, vehicle_capacity_kg, placed, start_time=start_time)
            if result is None:
                route = route + [job.pickup_idx, job.delivery_idx]
            else:
                pickup_pos, delivery_pos, _ = result
                route = insert_pair(route, job, pickup_pos, delivery_pos)
        placed.append(job)
    return route


def _destroy(
    route: list[int], jobs: list[Job], fraction: float, rng: random.Random
) -> tuple[list[int], list[Job]]:
    """Removes a random subset of jobs AS COMPLETE PAIRS - both the pickup and
    delivery stop of a chosen job are removed together, never split apart."""
    num_to_remove = max(1, round(len(jobs) * fraction))
    removed_jobs = rng.sample(jobs, min(num_to_remove, len(jobs)))
    removed_stops = {j.pickup_idx for j in removed_jobs} | {j.delivery_idx for j in removed_jobs}
    remaining_route = [stop for stop in route if stop not in removed_stops]
    return remaining_route, removed_jobs


def _repair(
    partial_route: list[int],
    all_jobs: list[Job],
    removed_jobs: list[Job],
    duration_matrix: Matrix,
    vehicle_capacity_kg: float | None,
    rng: random.Random,
    start_time: int = 0,
) -> list[int]:
    """Re-inserts each removed job, one at a time in randomized order, via
    best_pair_insertion - each job goes back in as a pickup+delivery unit."""
    route = list(partial_route)
    remaining_jobs = [j for j in all_jobs if j not in removed_jobs]
    order = list(removed_jobs)
    rng.shuffle(order)
    for job in order:
        result = best_pair_insertion(route, job, duration_matrix, vehicle_capacity_kg, remaining_jobs, start_time=start_time)
        if result is None:
            route = route + [job.pickup_idx, job.delivery_idx]
        else:
            pickup_pos, delivery_pos, _ = result
            route = insert_pair(route, job, pickup_pos, delivery_pos)
        remaining_jobs.append(job)
    return route


def solve(
    jobs: list[Job],
    duration_matrix: Matrix,
    distance_matrix: Matrix,
    vehicle_capacity_kg: float | None = None,
    iterations: int = 200,
    destroy_fraction: float = 0.25,
    seed: int | None = None,
    start_time: int = 0,
) -> SolveResult:
    """Constructs a route via cheapest-insertion, then improves it with
    `iterations` rounds of pair-atomic destroy-and-repair (LNS), keeping the
    best feasible route found. Never returns without the internal feasibility
    assertion passing - callers (including hybrid_solver's exact fallback)
    rely on that guarantee."""
    if not jobs:
        raise ValueError("solve() requires at least one job")

    rng = random.Random(seed)
    best_route = construct_greedy(jobs, duration_matrix, vehicle_capacity_kg, start_time)
    best_cost = route_total_cost(best_route, duration_matrix, jobs, vehicle_capacity_kg, start_time)

    for _ in range(iterations):
        partial_route, removed_jobs = _destroy(best_route, jobs, destroy_fraction, rng)
        candidate_route = _repair(partial_route, jobs, removed_jobs, duration_matrix, vehicle_capacity_kg, rng, start_time)
        candidate_cost = route_total_cost(candidate_route, duration_matrix, jobs, vehicle_capacity_kg, start_time)
        if candidate_cost == float('inf'):
            continue
        if candidate_cost < best_cost:
            best_route = candidate_route
            best_cost = candidate_cost

    total_lateness = route_is_feasible(best_route, jobs, vehicle_capacity_kg, duration_matrix, start_time)
    feasible = total_lateness != float('inf')
    assert feasible, "opt.solve() produced an infeasible route for a supposedly satisfiable instance"

    return SolveResult(
        route=best_route,
        total_duration_seconds=route_cost(best_route, duration_matrix),
        total_distance_meters=route_distance(best_route, distance_matrix),
        feasible=feasible,
        total_lateness_seconds=total_lateness if feasible else 0.0,
        solver_used="exact",
    )
