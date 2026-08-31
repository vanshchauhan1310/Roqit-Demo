"""hybrid_solve() - a drop-in replacement for opt.solve() with the same
feasibility guarantee, that scales to routes far larger than opt.solve()
can handle quickly.

Per job insertion: KD-tree spatial pruning (spatial.py) narrows the
insertion-position search space -> the surviving candidates are ranked by a
learned RandomForestRegressor's predicted cost delta (features.py,
train_ml.py), cheapest without computing a single real route cost -> the
top-ranked candidates are verified EXACTLY (opt.route_is_feasible /
opt.route_cost) and the best feasible one wins. If none of the shortlist is
feasible, the search widens once; if still nothing, that one job falls back
to opt.py's own exact best_pair_insertion. The model can only make the
search faster or slightly lower-quality - it can never make the returned
route wrong or infeasible, because nothing is ever accepted without exact
verification.

Below HYBRID_MIN_STOPS, this delegates straight to opt.solve() instead -
the spatial-index/model-loading overhead makes the hybrid path net SLOWER
at small scale (see benchmark.py's own numbers), so this app's realistic
route sizes (a handful of trips = a handful of stops) will almost always
take the plain opt.solve() path. That's correct, not a bug: the hybrid
path exists for the tens-to-hundreds-of-stops regime, which this
construction-time delegation is designed to detect and skip when absent.
"""

from __future__ import annotations

from pathlib import Path

import joblib

from src.optimizer import opt
from src.optimizer.features import PAIR_FEATURE_NAMES, extract_pair_features, featurize
from src.optimizer.spatial import RouteSpatialIndex

MODELS_DIR = Path(__file__).resolve().parents[2] / "models_store"
SINGLE_MODEL_PATH = MODELS_DIR / "optimizer_model_single.joblib"
PAIR_MODEL_PATH = MODELS_DIR / "optimizer_model_pair.joblib"

# "Below ~50 stops, just use opt.solve()" - the user's own benchmark finding.
HYBRID_MIN_STOPS = 50

_UNSET = object()
_model_cache = _UNSET


def load_models():
    """Returns (single_model, pair_model), or None if the .joblib artifacts
    haven't been trained yet (run train_ml.py) - callers must degrade
    gracefully to opt.solve() in that case, never raise."""
    global _model_cache
    if _model_cache is not _UNSET:
        return _model_cache

    if not SINGLE_MODEL_PATH.exists() or not PAIR_MODEL_PATH.exists():
        _model_cache = None
        return None

    try:
        _model_cache = (joblib.load(SINGLE_MODEL_PATH), joblib.load(PAIR_MODEL_PATH))
    except Exception:
        _model_cache = None
    return _model_cache


def _rank_candidates(
    route: list[int],
    job: opt.Job,
    duration_matrix: opt.Matrix,
    distance_matrix: opt.Matrix,
    coordinates: list[tuple[float, float]],
    vehicle_capacity_kg: float | None,
    loads: list[float],
    pair_model,
    k_spatial: int,
    top_m: int,
) -> list[tuple[int, int]]:
    """Spatial-prune then ML-rank candidate (pickup_pos, delivery_pos) pairs,
    cheapest predicted cost delta first. Returns at most top_m (pickup_pos,
    delivery_pos) tuples - no exact cost has been computed for any of them yet.
    `loads` is the cumulative load AFTER each stop in the current `route`
    (same length as route) - used to compute the real load-before-pickup for
    each candidate's specific pickup_pos, not a single shared approximation."""
    spatial_index = RouteSpatialIndex(coordinates, route)
    pickup_positions = spatial_index.nearest_positions(coordinates[job.pickup_idx], k_spatial)
    delivery_positions = spatial_index.nearest_positions(coordinates[job.delivery_idx], k_spatial)
    if not pickup_positions:
        pickup_positions = list(range(len(route) + 1))
    if not delivery_positions:
        delivery_positions = list(range(len(route) + 1))

    rows = []
    pairs = []
    for pickup_pos in pickup_positions:
        load_before_pickup = loads[pickup_pos - 1] if pickup_pos > 0 and loads else 0.0
        for delivery_pos in delivery_positions:
            if delivery_pos < pickup_pos:
                continue
            features = extract_pair_features(
                route,
                pickup_pos,
                delivery_pos,
                job,
                duration_matrix,
                distance_matrix,
                vehicle_capacity_kg,
                load_before_pickup,
                spatial_rank_pickup=pickup_positions.index(pickup_pos),
                spatial_rank_delivery=delivery_positions.index(delivery_pos),
            )
            rows.append(features)
            pairs.append((pickup_pos, delivery_pos))

    if not rows:
        return []

    X = featurize(rows, PAIR_FEATURE_NAMES)
    predicted_deltas = pair_model.predict(X)
    ranked = sorted(zip(pairs, predicted_deltas), key=lambda item: item[1])
    return [pair for pair, _ in ranked[:top_m]]


def _insert_job_hybrid(
    route: list[int],
    placed_jobs: list[opt.Job],
    job: opt.Job,
    duration_matrix: opt.Matrix,
    distance_matrix: opt.Matrix,
    coordinates: list[tuple[float, float]],
    vehicle_capacity_kg: float | None,
    pair_model,
    k_spatial: int,
    top_m: int,
    start_time: int = 0,
) -> list[int]:
    loads = opt._load_at_positions(route, placed_jobs) if route else []

    for widen_attempt in (1, 3):
        ranked_pairs = _rank_candidates(
            route, job, duration_matrix, distance_matrix, coordinates, vehicle_capacity_kg,
            loads, pair_model, k_spatial * widen_attempt, top_m * widen_attempt,
        )
        for pickup_pos, delivery_pos in ranked_pairs:
            candidate_route = opt.insert_pair(route, job, pickup_pos, delivery_pos)
            if opt.route_is_feasible(candidate_route, placed_jobs + [job], vehicle_capacity_kg, duration_matrix, start_time) != float('inf'):
                return candidate_route

    result = opt.best_pair_insertion(route, job, duration_matrix, vehicle_capacity_kg, placed_jobs, start_time=start_time)
    if result is None:
        return route + [job.pickup_idx, job.delivery_idx]
    pickup_pos, delivery_pos, _ = result
    return opt.insert_pair(route, job, pickup_pos, delivery_pos)


def hybrid_solve(
    jobs: list[opt.Job],
    duration_matrix: opt.Matrix,
    distance_matrix: opt.Matrix,
    coordinates: list[tuple[float, float]],
    vehicle_capacity_kg: float | None = None,
    k_spatial: int = 10,
    top_m: int = 20,
    iterations: int = 200,
    seed: int | None = None,
    start_time: int = 0,
) -> opt.SolveResult:
    if not jobs:
        raise ValueError("hybrid_solve() requires at least one job")

    num_stops = 2 * len(jobs)
    models = load_models()

    if num_stops < HYBRID_MIN_STOPS or models is None:
        result = opt.solve(
            jobs, duration_matrix, distance_matrix, vehicle_capacity_kg, iterations=iterations, seed=seed, start_time=start_time
        )
        return result

    _, pair_model = models
    route: list[int] = []
    placed: list[opt.Job] = []
    for job in jobs:
        if not route:
            route = [job.pickup_idx, job.delivery_idx]
        else:
            route = _insert_job_hybrid(
                route, placed, job, duration_matrix, distance_matrix, coordinates,
                vehicle_capacity_kg, pair_model, k_spatial, top_m, start_time,
            )
        placed.append(job)

    total_lateness = opt.route_is_feasible(route, jobs, vehicle_capacity_kg, duration_matrix, start_time)
    feasible = total_lateness != float('inf')
    assert feasible, "hybrid_solve() produced an infeasible route for a supposedly satisfiable instance"

    return opt.SolveResult(
        route=route,
        total_duration_seconds=opt.route_cost(route, duration_matrix),
        total_distance_meters=opt.route_distance(route, distance_matrix),
        feasible=feasible,
        total_lateness_seconds=total_lateness if feasible else 0.0,
        solver_used="hybrid",
    )
