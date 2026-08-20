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


@dataclass
class Job:
    trip_id: str
    pickup_idx: int
    delivery_idx: int
    load_weight_kg: float = 0.0


@dataclass
class SolveResult:
    route: list[int]
    total_duration_seconds: float
    total_distance_meters: float
    feasible: bool
    solver_used: Literal["exact", "hybrid"] = "exact"


def route_cost(route: list[int], duration_matrix: Matrix) -> float:
    return sum(duration_matrix[route[i]][route[i + 1]] for i in range(len(route) - 1))


def route_distance(route: list[int], distance_matrix: Matrix) -> float:
    return sum(distance_matrix[route[i]][route[i + 1]] for i in range(len(route) - 1))


def route_is_feasible(route: list[int], jobs: list[Job], vehicle_capacity_kg: float | None) -> bool:
    """A route is feasible iff every job's pickup precedes its own delivery,
    and (when vehicle_capacity_kg is given) cumulative load never exceeds it
    at any point along the route. vehicle_capacity_kg=None means unconstrained
    - used when the vehicle/its capacity isn't known yet at optimize-time."""
    if len(route) != len(set(route)):
        return False

    position = {stop: i for i, stop in enumerate(route)}
    for job in jobs:
        if job.pickup_idx not in position or job.delivery_idx not in position:
            return False
        if position[job.pickup_idx] >= position[job.delivery_idx]:
            return False

    if vehicle_capacity_kg is not None:
        for load in _load_at_positions(route, jobs):
            if load > vehicle_capacity_kg + 1e-9 or load < -1e-9:
                return False

    return True


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
) -> tuple[int, int, float] | None:
    """Exhaustive search over every feasible (pickup_pos, delivery_pos) pair -
    O(n^2) candidate positions in len(route) by default. Pass
    pickup_positions/delivery_positions (each a list of original-route
    indices) to restrict the search to a pruned candidate set instead - used
    by hybrid_solver's spatially-pruned path. Returns (pickup_pos,
    delivery_pos, added_cost) for the cheapest FEASIBLE insertion found, or
    None if nothing in the searched candidate set is feasible."""
    n = len(route)
    base_cost = route_cost(route, duration_matrix)
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
            if not route_is_feasible(candidate_route, placed_jobs + [job], vehicle_capacity_kg):
                continue
            added_cost = route_cost(candidate_route, duration_matrix) - base_cost
            if best is None or added_cost < best[2]:
                best = (pickup_pos, delivery_pos, added_cost)
    return best


def construct_greedy(jobs: list[Job], duration_matrix: Matrix, vehicle_capacity_kg: float | None) -> list[int]:
    """Builds a route from empty by inserting jobs one at a time, in input
    order, at each job's cheapest feasible position (cheapest insertion
    heuristic)."""
    route: list[int] = []
    placed: list[Job] = []
    for job in jobs:
        if not route:
            route = [job.pickup_idx, job.delivery_idx]
        else:
            result = best_pair_insertion(route, job, duration_matrix, vehicle_capacity_kg, placed)
            if result is None:
                # No feasible slot anywhere (e.g. this job's own weight can never
                # fit) - append unconstrained rather than silently drop the job.
                # solve()'s final feasibility assertion is the real safety net:
                # if the instance is genuinely infeasible, it fails loudly here
                # instead of returning a route that quietly violates capacity.
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
) -> list[int]:
    """Re-inserts each removed job, one at a time in randomized order, via
    best_pair_insertion - each job goes back in as a pickup+delivery unit."""
    route = list(partial_route)
    remaining_jobs = [j for j in all_jobs if j not in removed_jobs]
    order = list(removed_jobs)
    rng.shuffle(order)
    for job in order:
        result = best_pair_insertion(route, job, duration_matrix, vehicle_capacity_kg, remaining_jobs)
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
) -> SolveResult:
    """Constructs a route via cheapest-insertion, then improves it with
    `iterations` rounds of pair-atomic destroy-and-repair (LNS), keeping the
    best feasible route found. Never returns without the internal feasibility
    assertion passing - callers (including hybrid_solver's exact fallback)
    rely on that guarantee."""
    if not jobs:
        raise ValueError("solve() requires at least one job")

    rng = random.Random(seed)
    best_route = construct_greedy(jobs, duration_matrix, vehicle_capacity_kg)
    best_cost = route_cost(best_route, duration_matrix)

    for _ in range(iterations):
        partial_route, removed_jobs = _destroy(best_route, jobs, destroy_fraction, rng)
        candidate_route = _repair(partial_route, jobs, removed_jobs, duration_matrix, vehicle_capacity_kg, rng)
        if not route_is_feasible(candidate_route, jobs, vehicle_capacity_kg):
            continue
        candidate_cost = route_cost(candidate_route, duration_matrix)
        if candidate_cost < best_cost:
            best_route = candidate_route
            best_cost = candidate_cost

    feasible = route_is_feasible(best_route, jobs, vehicle_capacity_kg)
    assert feasible, "opt.solve() produced an infeasible route for a supposedly satisfiable instance"

    return SolveResult(
        route=best_route,
        total_duration_seconds=route_cost(best_route, duration_matrix),
        total_distance_meters=route_distance(best_route, distance_matrix),
        feasible=feasible,
        solver_used="exact",
    )
