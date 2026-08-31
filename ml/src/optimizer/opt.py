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
    # Optional metadata used only by fleet splitting.  The original job weight
    # is retained separately; this value is the part assigned to a vehicle.
    parent_trip_id: str | None = None
    original_load_weight_kg: float | None = None
    allowed_vehicle_ids: frozenset[str] | None = None


@dataclass
class SolveResult:
    route: list[int]
    total_duration_seconds: float
    total_distance_meters: float
    feasible: bool
    solver_used: Literal["exact", "hybrid"] = "exact"


@dataclass
class CostWeights:
    """Blends the optimizer's multi-objective: J(R) = alpha*D_hat + beta*F_hat + gamma*L_hat +
    delta*Dist_hat, where each _hat term is baseline-normalized (see RouteBaselines /
    weighted_route_cost) so distance/duration/fuel/ton-km - four quantities on wildly different
    scales (meters, seconds, currency, tonne-km) - become directly comparable before being
    combined. Defaults (beta=gamma=delta=0) make weighted_route_cost() reduce to
    alpha*route_cost() - i.e. today's pure-duration behavior - so any caller not passing this is
    unaffected. avg_kmpl_rated/fuel_price_per_l are only consulted when beta != 0 (see
    estimate_fuel_cost: missing either just makes the fuel term 0, never raises)."""

    alpha: float = 1.0  # duration
    beta: float = 0.0  # fuel cost
    gamma: float = 0.0  # ton-km (load x distance)
    delta: float = 0.0  # distance
    avg_kmpl_rated: float | None = None
    fuel_price_per_l: float | None = None

    def is_multi_objective(self) -> bool:
        return self.beta != 0.0 or self.gamma != 0.0 or self.delta != 0.0


DEFAULT_COST_WEIGHTS = CostWeights()


@dataclass
class RouteBaselines:
    """Reference scale for each objective term, so J(R) combines dimensionless ratios (term/
    baseline) instead of raw meters+seconds+currency+tonne-km. Computed once per solve() call from
    a cheap duration-only reference route (compute_baselines) - not from the candidate route being
    scored, since normalizing a route against itself would always yield 1.0 and destroy all
    differentiation between candidates."""

    duration: float
    distance_km: float
    fuel_cost: float
    ton_km: float


_BASELINE_FLOOR = 1e-6  # avoids division by zero when a term's reference value is legitimately 0

# Heuristic linear mileage derating under load (e.g. 0.03 = 3% less km/l per tonne carried) - not
# a physics model, a cheap proxy so heavier legs cost more without a per-edge call into the
# trained fuel-consumption model (that model needs weather/road/traffic fields that don't exist
# per OSRM matrix edge, and is far too slow to call from inside the LNS hot loop - see opt.py's
# module docstring / WEIGHT_AWARE_ROUTING.md §3 for the full reasoning).
LOAD_KMPL_DERATE_PER_TONNE = 0.03
MIN_KMPL_FRACTION_OF_RATED = 0.4  # floor so effective mileage never craters toward 0 under a huge load


def route_cost(route: list[int], duration_matrix: Matrix) -> float:
    return sum(duration_matrix[route[i]][route[i + 1]] for i in range(len(route) - 1))


def route_distance(route: list[int], distance_matrix: Matrix) -> float:
    return sum(distance_matrix[route[i]][route[i + 1]] for i in range(len(route) - 1))


def estimate_fuel_cost(distance_km: float, load_on_leg_kg: float, weights: CostWeights) -> float:
    """Closed-form fuel-cost proxy for one edge. Returns 0.0 if the vehicle's mileage/fuel price
    aren't known, so beta > 0 with no vehicle info degrades to "no fuel term" rather than
    raising."""
    if weights.avg_kmpl_rated is None or weights.fuel_price_per_l is None or weights.avg_kmpl_rated <= 0:
        return 0.0
    load_factor = 1.0 + LOAD_KMPL_DERATE_PER_TONNE * (load_on_leg_kg / 1000.0)
    effective_kmpl = max(
        weights.avg_kmpl_rated / load_factor,
        weights.avg_kmpl_rated * MIN_KMPL_FRACTION_OF_RATED,
    )
    fuel_liters = distance_km / effective_kmpl
    return fuel_liters * weights.fuel_price_per_l


def route_components(
    route: list[int],
    duration_matrix: Matrix,
    distance_matrix: Matrix,
    jobs: list["Job"],
    weights: CostWeights,
) -> tuple[float, float, float, float]:
    """Raw (unnormalized) (duration, distance_km, fuel_cost, ton_km) totals for `route`.
    load_on_leg (whatever cargo is aboard while traversing one edge) is NOT a static property of
    that edge - it depends on which pickups/deliveries already happened earlier in THIS specific
    route - so these totals are recomputed per candidate route via _load_at_positions, never
    looked up from a precomputed matrix (see WEIGHT_AWARE_ROUTING.md §4). fuel_cost/ton_km are
    only accumulated when their weight is non-zero, since ton_km is free but fuel_cost calls
    estimate_fuel_cost per edge."""
    loads = _load_at_positions(route, jobs)
    total_duration = 0.0
    total_distance_km = 0.0
    total_fuel_cost = 0.0
    total_ton_km = 0.0
    for k in range(len(route) - 1):
        i, j = route[k], route[k + 1]
        load_on_leg = loads[k] if k < len(loads) else 0.0
        distance_km = distance_matrix[i][j] / 1000.0  # OSRM /table distances are meters
        total_duration += duration_matrix[i][j]
        total_distance_km += distance_km
        if weights.beta:
            total_fuel_cost += estimate_fuel_cost(distance_km, load_on_leg, weights)
        if weights.gamma:
            total_ton_km += (load_on_leg / 1000.0) * distance_km
    return total_duration, total_distance_km, total_fuel_cost, total_ton_km


def compute_baselines(
    jobs: list["Job"],
    duration_matrix: Matrix,
    distance_matrix: Matrix,
    weights: CostWeights,
) -> RouteBaselines:
    """Reference scale for normalization: build one cheap duration-only route (unconstrained by
    capacity - it only exists to set a scale, never returned as an actual answer) and use ITS raw
    totals as the denominator each candidate's totals get divided by. Computed once per solve()/
    hybrid_solve() call, not per candidate - a per-candidate baseline would always normalize a
    route against itself (ratio 1.0) and destroy all differentiation between candidates."""
    reference_route = construct_greedy(jobs, duration_matrix, None)
    duration, distance_km, fuel_cost, ton_km = route_components(
        reference_route, duration_matrix, distance_matrix, jobs, weights
    )
    return RouteBaselines(
        duration=max(duration, _BASELINE_FLOOR),
        distance_km=max(distance_km, _BASELINE_FLOOR),
        fuel_cost=max(fuel_cost, _BASELINE_FLOOR),
        ton_km=max(ton_km, _BASELINE_FLOOR),
    )


def weighted_route_cost(
    route: list[int],
    duration_matrix: Matrix,
    distance_matrix: Matrix | None,
    jobs: list["Job"] | None,
    weights: CostWeights | None = None,
    baselines: RouteBaselines | None = None,
) -> float:
    """The optimizer's actual objective - construction and LNS acceptance compare candidates on
    this, not on route_cost() directly. Reduces to exactly alpha*route_cost() when
    beta=gamma=delta=0 (the default), so weights=None/DEFAULT_COST_WEIGHTS callers see identical
    route choices to before this existed. distance_matrix/jobs may be None only in that same
    all-zero case.

    When `baselines` is given, each raw component is divided by its baseline before being
    weighted - J(R) = alpha*(D/D0) + delta*(Dist/Dist0) + beta*(F/F0) + gamma*(L/L0) - so the
    weights are genuinely comparable business-priority percentages (e.g. 20/25/40/15) rather than
    an ad-hoc mix of raw seconds, meters, currency and tonne-km. Without `baselines`, terms are
    combined raw (backward-compatible with callers that pre-date normalization)."""
    weights = weights or DEFAULT_COST_WEIGHTS
    if not weights.is_multi_objective():
        return weights.alpha * route_cost(route, duration_matrix)

    duration, distance_km, fuel_cost, ton_km = route_components(
        route, duration_matrix, distance_matrix, jobs or [], weights
    )
    if baselines is None:
        return weights.alpha * duration + weights.delta * distance_km + weights.beta * fuel_cost + weights.gamma * ton_km

    return (
        weights.alpha * (duration / baselines.duration)
        + weights.delta * (distance_km / baselines.distance_km)
        + weights.beta * (fuel_cost / baselines.fuel_cost)
        + weights.gamma * (ton_km / baselines.ton_km)
    )


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
    distance_matrix: Matrix | None = None,
    weights: CostWeights | None = None,
    baselines: RouteBaselines | None = None,
) -> tuple[int, int, float] | None:
    """Exhaustive search over every feasible (pickup_pos, delivery_pos) pair -
    O(n^2) candidate positions in len(route) by default. Pass
    pickup_positions/delivery_positions (each a list of original-route
    indices) to restrict the search to a pruned candidate set instead - used
    by hybrid_solver's spatially-pruned path. Returns (pickup_pos,
    delivery_pos, added_cost) for the cheapest FEASIBLE insertion found, or
    None if nothing in the searched candidate set is feasible.

    distance_matrix/weights are optional - pass both together (any of
    weights.beta/.gamma/.delta non-zero) to score candidates via
    weighted_route_cost() instead of plain duration; omitted, behavior is
    identical to before these params existed. `baselines`, if given, is
    forwarded so weighted scoring is normalized (see weighted_route_cost)."""
    n = len(route)
    is_weighted = weights is not None and weights.is_multi_objective()
    all_jobs = placed_jobs + [job]

    def _cost(r: list[int]) -> float:
        if is_weighted:
            return weighted_route_cost(r, duration_matrix, distance_matrix, all_jobs, weights, baselines)
        return route_cost(r, duration_matrix)

    base_cost = _cost(route)
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
            if not route_is_feasible(candidate_route, all_jobs, vehicle_capacity_kg):
                continue
            added_cost = _cost(candidate_route) - base_cost
            if best is None or added_cost < best[2]:
                best = (pickup_pos, delivery_pos, added_cost)
    return best


def construct_greedy(
    jobs: list[Job],
    duration_matrix: Matrix,
    vehicle_capacity_kg: float | None,
    distance_matrix: Matrix | None = None,
    weights: CostWeights | None = None,
    baselines: RouteBaselines | None = None,
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
            result = best_pair_insertion(
                route, job, duration_matrix, vehicle_capacity_kg, placed,
                distance_matrix=distance_matrix, weights=weights, baselines=baselines,
            )
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
    distance_matrix: Matrix | None = None,
    weights: CostWeights | None = None,
    baselines: RouteBaselines | None = None,
) -> list[int]:
    """Re-inserts each removed job, one at a time in randomized order, via
    best_pair_insertion - each job goes back in as a pickup+delivery unit."""
    route = list(partial_route)
    remaining_jobs = [j for j in all_jobs if j not in removed_jobs]
    order = list(removed_jobs)
    rng.shuffle(order)
    for job in order:
        result = best_pair_insertion(
            route, job, duration_matrix, vehicle_capacity_kg, remaining_jobs,
            distance_matrix=distance_matrix, weights=weights, baselines=baselines,
        )
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
    weights: CostWeights | None = None,
) -> SolveResult:
    """Constructs a route via cheapest-insertion, then improves it with
    `iterations` rounds of pair-atomic destroy-and-repair (LNS), keeping the
    best feasible route found (by weighted_route_cost() - reduces to plain
    duration when weights is None/default). Never returns without the
    internal feasibility assertion passing - callers (including
    hybrid_solver's exact fallback) rely on that guarantee. Reported
    total_duration_seconds/total_distance_meters are always the plain
    (unweighted) totals for the chosen route, regardless of what weights
    were used to select it."""
    if not jobs:
        raise ValueError("solve() requires at least one job")

    weights = weights or DEFAULT_COST_WEIGHTS
    # Baselines are computed ONCE, up front, from a cheap duration-only reference route - not
    # per-candidate (see compute_baselines) - so every comparison during construction/LNS below
    # uses the same fixed scale.
    baselines = compute_baselines(jobs, duration_matrix, distance_matrix, weights) if weights.is_multi_objective() else None

    rng = random.Random(seed)
    best_route = construct_greedy(jobs, duration_matrix, vehicle_capacity_kg, distance_matrix, weights, baselines)
    best_cost = weighted_route_cost(best_route, duration_matrix, distance_matrix, jobs, weights, baselines)

    for _ in range(iterations):
        partial_route, removed_jobs = _destroy(best_route, jobs, destroy_fraction, rng)
        candidate_route = _repair(
            partial_route, jobs, removed_jobs, duration_matrix, vehicle_capacity_kg, rng,
            distance_matrix=distance_matrix, weights=weights, baselines=baselines,
        )
        if not route_is_feasible(candidate_route, jobs, vehicle_capacity_kg):
            continue
        candidate_cost = weighted_route_cost(candidate_route, duration_matrix, distance_matrix, jobs, weights, baselines)
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
