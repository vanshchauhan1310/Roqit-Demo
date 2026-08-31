#!/usr/bin/env python
"""Run simulation from CSV data."""

import argparse
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.simulation.engine import run_simulation, run_comparison


def main():
    parser = argparse.ArgumentParser(description="Run route optimization simulation")
    parser.add_argument("csv_path", help="Path to CSV file with trip data")
    parser.add_argument("--speed", type=float, default=1.0, help="Replay speed factor")
    parser.add_argument("--lns-interval", type=int, default=0, help="Run LNS every N trips (0=disabled)")
    parser.add_argument("--compare", action="store_true", help="Run greedy vs LNS comparison")

    args = parser.parse_args()

    if args.compare:
        print("Running greedy vs LNS comparison...")
        results = run_comparison(args.csv_path)
        greedy = results["greedy_only"]
        lns = results["greedy_plus_lns"]

        print("\n=== GREEDY ONLY ===")
        print(f"  Trips processed: {greedy.trips_processed}")
        print(f"  Trips assigned: {greedy.trips_assigned}")
        print(f"  Trips unassigned: {greedy.trips_unassigned}")
        print(f"  Routes created: {greedy.routes_created}")
        print(f"  Total distance: {greedy.total_distance_km:.2f} km")
        print(f"  Avg distance/trip: {greedy.avg_distance_per_trip:.2f} km")
        print(f"  Route utilization: {greedy.route_utilization:.1%}")
        print(f"  Total cost: {greedy.greedy_cost:.2f}")
        print(f"  Avg assignment latency: {greedy.assignment_latency_ms / max(greedy.trips_processed, 1):.2f} ms")

        print("\n=== GREEDY + LNS ===")
        print(f"  Trips processed: {lns.trips_processed}")
        print(f"  Trips assigned: {lns.trips_assigned}")
        print(f"  Trips unassigned: {lns.trips_unassigned}")
        print(f"  Routes created: {lns.routes_created}")
        print(f"  Total distance: {lns.total_distance_km:.2f} km")
        print(f"  Avg distance/trip: {lns.avg_distance_per_trip:.2f} km")
        print(f"  Route utilization: {lns.route_utilization:.1%}")
        print(f"  Total cost: {lns.final_lns_cost:.2f}")
        print(f"  Improvement: {lns.improvement_percentage:.2f}%")
        print(f"  Avg assignment latency: {lns.assignment_latency_ms / max(lns.trips_processed, 1):.2f} ms")
    else:
        print(f"Running simulation from {args.csv_path}...")
        result = run_simulation(
            args.csv_path,
            speed_factor=args.speed,
            run_lns_every_n_trips=args.lns_interval,
        )

        print("\n=== SIMULATION RESULTS ===")
        print(f"  Trips processed: {result.trips_processed}")
        print(f"  Trips assigned: {result.trips_assigned}")
        print(f"  Trips unassigned: {result.trips_unassigned}")
        print(f"  Routes created: {result.routes_created}")
        print(f"  Total distance: {result.total_distance_km:.2f} km")
        print(f"  Total duration: {result.total_duration_minutes:.2f} min")
        print(f"  Avg distance/trip: {result.avg_distance_per_trip:.2f} km")
        print(f"  Avg delay: {result.avg_delay_minutes:.2f} min")
        print(f"  Total fuel cost: {result.total_fuel_cost:.2f}")
        print(f"  Route utilization: {result.route_utilization:.1%}")
        print(f"  Avg assignment latency: {result.assignment_latency_ms / max(result.trips_processed, 1):.2f} ms")


if __name__ == "__main__":
    main()