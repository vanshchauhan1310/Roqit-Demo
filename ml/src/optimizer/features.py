"""Feature extraction for insertion candidates - shared by train_ml.py
(labeling) and hybrid_solver.py (serving), the same way
ml/src/features/build_features.py's COST_FEATURE_ORDER is shared between
training and serving for the other models in this repo. Every feature here
is deliberately O(1) given a route/position - this module is what makes
hybrid_solver's ranking step cheap; the exact cost math stays in opt.py.
"""

from __future__ import annotations

import pandas as pd

from src.optimizer.opt import Job, Matrix, insertion_delta, route_cost

# Large finite stand-in for "no capacity constraint given" (vehicle_capacity_kg=None)
# so headroom is still a well-defined, comparable number across training examples.
UNCONSTRAINED_HEADROOM_KG = 1_000_000.0

SINGLE_FEATURE_NAMES: list[str] = [
    "detour_cost",
    "load_before",
    "load_headroom_before",
    "downstream_distance",
    "position_fraction",
    "route_length_so_far",
    "num_jobs_placed",
]

PAIR_FEATURE_NAMES: list[str] = [
    "pickup_detour_cost",
    "delivery_detour_cost",
    "pickup_to_delivery_direct_distance",
    "load_before_pickup",
    "load_headroom_before_pickup",
    "position_fraction_pickup",
    "position_fraction_delivery",
    "gap_positions",
    "downstream_distance_from_pickup",
    "downstream_distance_from_delivery",
    "route_length_so_far",
    "num_jobs_placed",
    "spatial_rank_pickup",
    "spatial_rank_delivery",
    "fuel_rate_proxy",
]


def _headroom(vehicle_capacity_kg: float | None, load_before: float) -> float:
    if vehicle_capacity_kg is None:
        return UNCONSTRAINED_HEADROOM_KG
    return vehicle_capacity_kg - load_before


def _downstream_distance(route: list[int], position: int, distance_matrix: Matrix) -> float:
    """Cheap O(1) proxy for 'how much route is left after this point', not an
    exact recomputation: straight-line-in-matrix-terms distance from the stop
    at `position` to the route's current last stop."""
    if not route or position >= len(route):
        return 0.0
    return distance_matrix[route[position]][route[-1]]


def extract_single_features(
    route: list[int],
    position: int,
    stop_idx: int,
    duration_matrix: Matrix,
    distance_matrix: Matrix,
    vehicle_capacity_kg: float | None,
    cumulative_load_before: float,
) -> dict[str, float]:
    """Features for inserting ONE stop (a pickup or delivery in isolation) at
    `position`. Used for LNS repair of a lone stop; the main construction
    path uses extract_pair_features since jobs are inserted as units."""
    return {
        "detour_cost": insertion_delta(route, position, stop_idx, duration_matrix),
        "load_before": cumulative_load_before,
        "load_headroom_before": _headroom(vehicle_capacity_kg, cumulative_load_before),
        "downstream_distance": _downstream_distance(route, position, distance_matrix),
        "position_fraction": position / max(len(route), 1),
        "route_length_so_far": route_cost(route, duration_matrix),
        "num_jobs_placed": len(route) // 2,
    }


def extract_pair_features(
    route: list[int],
    pickup_pos: int,
    delivery_pos: int,
    job: Job,
    duration_matrix: Matrix,
    distance_matrix: Matrix,
    vehicle_capacity_kg: float | None,
    cumulative_load_before_pickup: float,
    spatial_rank_pickup: int,
    spatial_rank_delivery: int,
) -> dict[str, float]:
    """Features for inserting a job's (pickup, delivery) pair as a unit at
    (pickup_pos, delivery_pos) - both indices in the ORIGINAL route's index
    space, same convention as opt.best_pair_insertion/insert_pair."""
    route_with_pickup = route[:pickup_pos] + [job.pickup_idx] + route[pickup_pos:]

    return {
        "pickup_detour_cost": insertion_delta(route, pickup_pos, job.pickup_idx, duration_matrix),
        "delivery_detour_cost": insertion_delta(
            route_with_pickup, delivery_pos + 1, job.delivery_idx, duration_matrix
        ),
        "pickup_to_delivery_direct_distance": distance_matrix[job.pickup_idx][job.delivery_idx],
        "load_before_pickup": cumulative_load_before_pickup,
        "load_headroom_before_pickup": _headroom(vehicle_capacity_kg, cumulative_load_before_pickup),
        "position_fraction_pickup": pickup_pos / max(len(route), 1),
        "position_fraction_delivery": delivery_pos / max(len(route), 1),
        "gap_positions": delivery_pos - pickup_pos,
        "downstream_distance_from_pickup": _downstream_distance(route, pickup_pos, distance_matrix),
        "downstream_distance_from_delivery": _downstream_distance(route, delivery_pos, distance_matrix),
        "route_length_so_far": route_cost(route, duration_matrix),
        "num_jobs_placed": len(route) // 2,
        "spatial_rank_pickup": spatial_rank_pickup,
        "spatial_rank_delivery": spatial_rank_delivery,
        # No real fuel-consumption model is wired into this pure combinatorial
        # optimizer (that lives in ml/src/models/fuel_consumption.py, which
        # needs vehicle/weather/road fields this module doesn't have) - this
        # is a cheap load-weight-based proxy: heavier cargo costs more per km.
        "fuel_rate_proxy": job.load_weight_kg,
    }


def featurize(rows: list[dict[str, float]], feature_names: list[str]) -> pd.DataFrame:
    """Builds a DataFrame with columns in exactly `feature_names` order -
    the single source of truth both train_ml.py (fit) and hybrid_solver.py
    (predict) must go through, so column order can never drift between them."""
    return pd.DataFrame(rows, columns=feature_names)
