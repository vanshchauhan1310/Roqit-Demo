"""Offline exact-vs-hybrid comparison harness. NOT part of the live service -
not imported by ml_api.py or train_ml.py. Run manually to reproduce/update
the honest benchmark numbers documented for this feature.

Usage (from ml/, with its venv active):
    python -m src.optimizer.benchmark --stop-counts 10,20,40,60,80 --trials 3 --seed 1
"""

from __future__ import annotations

import argparse
import random
import time

import pandas as pd

from src.optimizer import opt
from src.optimizer.hybrid_solver import hybrid_solve
from src.optimizer.train_ml import _euclidean_matrix, random_jobs

DEFAULT_CAPACITY_KG = 8000.0


def _run_one(num_stops: int, seed: int) -> dict:
    num_jobs = max(1, num_stops // 2)
    rng = random.Random(seed)
    jobs, coordinates = random_jobs(num_jobs, rng)
    duration_matrix = _euclidean_matrix(coordinates)
    distance_matrix = duration_matrix

    t0 = time.perf_counter()
    exact_result = opt.solve(jobs, duration_matrix, distance_matrix, DEFAULT_CAPACITY_KG, seed=seed)
    exact_time = time.perf_counter() - t0

    t0 = time.perf_counter()
    hybrid_result = hybrid_solve(
        jobs, duration_matrix, distance_matrix, coordinates, DEFAULT_CAPACITY_KG, seed=seed
    )
    hybrid_time = time.perf_counter() - t0

    quality_gap_pct = (
        (hybrid_result.total_duration_seconds - exact_result.total_duration_seconds)
        / exact_result.total_duration_seconds
        * 100
        if exact_result.total_duration_seconds > 0
        else 0.0
    )

    return {
        "num_stops": num_jobs * 2,
        "exact_time_s": round(exact_time, 3),
        "hybrid_time_s": round(hybrid_time, 3),
        "exact_cost": round(exact_result.total_duration_seconds, 2),
        "hybrid_cost": round(hybrid_result.total_duration_seconds, 2),
        "quality_gap_pct": round(quality_gap_pct, 2),
        "hybrid_solver_used": hybrid_result.solver_used,
    }


def run_benchmark(stop_counts: list[int], trials_per_size: int, seed: int) -> pd.DataFrame:
    rows = []
    for num_stops in stop_counts:
        for trial in range(trials_per_size):
            rows.append(_run_one(num_stops, seed=seed + trial))
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Exact vs hybrid pickup-delivery optimizer benchmark")
    parser.add_argument("--stop-counts", type=str, default="10,20,40,60,80")
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--csv-out", type=str, default=None)
    args = parser.parse_args()

    stop_counts = [int(s) for s in args.stop_counts.split(",")]
    df = run_benchmark(stop_counts, args.trials, args.seed)

    summary = df.groupby("num_stops")[["exact_time_s", "hybrid_time_s", "quality_gap_pct"]].mean().round(2)
    print(summary.to_string())

    if args.csv_out:
        df.to_csv(args.csv_out, index=False)
        print(f"Wrote raw results to {args.csv_out}")


if __name__ == "__main__":
    main()
