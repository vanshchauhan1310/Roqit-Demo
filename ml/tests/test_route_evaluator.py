"""Regression tests for the sequential, dynamic multi-vehicle route evaluator."""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.optimizer.opt import Job  # noqa: E402
from src.optimizer.route_evaluator import (  # noqa: E402
    VehicleSpec,
    evaluate_fleet,
    evaluate_route,
    fleet_total_cost,
)


def _matrices(n, distance_m=10_000.0, duration_s=600.0):
    return (
        [[0.0 if i == j else duration_s for j in range(n)] for i in range(n)],
        [[0.0 if i == j else distance_m for j in range(n)] for i in range(n)],
    )


def _vehicle(**overrides):
    values = dict(vehicle_id="truck", capacity_kg=1_000, avg_kmpl_rated=10, fuel_price_per_l=100)
    values.update(overrides)
    return VehicleSpec(**values)


def test_load_changes_after_each_pickup_and_drop():
    dur, dist = _matrices(4)
    jobs = [Job("A", 0, 1, 400), Job("B", 2, 3, 300)]
    result = evaluate_route([0, 1, 2, 3], jobs, _vehicle(), dur, dist, datetime(2026, 1, 1), service_time_per_stop_s=0)
    assert [event.load_after for event in result.stop_events] == [400, 0, 300, 0]
    assert result.peak_load == 400


def test_peak_load_capacity_violation_is_infeasible():
    dur, dist = _matrices(4)
    jobs = [Job("A", 0, 1, 700), Job("B", 2, 3, 600)]
    result = evaluate_route([0, 2, 1, 3], jobs, _vehicle(), dur, dist, datetime(2026, 1, 1), service_time_per_stop_s=0)
    assert not result.feasible
    assert result.peak_load == 1_300
    assert "Capacity exceeded" in result.violation_reason


def test_load_ratio_changes_speed_and_fuel():
    dur, dist = _matrices(2)
    empty = evaluate_route([0, 1], [Job("empty", 0, 1, 0)], _vehicle(), dur, dist, datetime(2026, 1, 1), service_time_per_stop_s=0)
    loaded = evaluate_route([0, 1], [Job("loaded", 0, 1, 1_000)], _vehicle(), dur, dist, datetime(2026, 1, 1), service_time_per_stop_s=0)
    assert loaded.legs[0].speed_kmph < empty.legs[0].speed_kmph
    assert loaded.fuel_liters > empty.fuel_liters


def test_time_aware_factor_uses_the_updated_route_clock():
    dur, dist = _matrices(4, distance_m=30_000, duration_s=1_800)
    jobs = [Job("A", 0, 1, 0), Job("B", 2, 3, 0)]
    seen = []

    def time_factor(_from, _to, departure, _load_ratio):
        seen.append(departure)
        return 1.0 if departure.hour == 8 and departure.minute < 30 else 0.5

    result = evaluate_route([0, 1, 2, 3], jobs, _vehicle(), dur, dist, datetime(2026, 1, 1, 8), service_time_per_stop_s=0, get_speed_factor=time_factor)
    assert seen == [datetime(2026, 1, 1, 8), datetime(2026, 1, 1, 8, 30), datetime(2026, 1, 1, 9, 30)]
    # Factor is applied per leg (and not from a static matrix); use longer legs
    # so the final departure crosses the half-hour threshold.
    assert result.legs[-1].traffic_factor == 0.5


def test_driver_rate_is_charged_at_each_route_timestamp():
    dur, dist = _matrices(2, distance_m=60_000, duration_s=3_600)
    rate = lambda at: 10.0 if at.hour < 9 else 20.0
    result = evaluate_route([0, 1], [Job("A", 0, 1, 0)], _vehicle(), dur, dist, datetime(2026, 1, 1, 8), service_time_per_stop_s=0, get_driver_cost_per_hour=rate)
    assert result.driver_cost == 10.0


def test_fleet_cost_sums_only_used_vehicles_and_unused_fixed_cost_is_zero():
    dur, dist = _matrices(2)
    vehicles = {"used": _vehicle(vehicle_id="used", fixed_cost=50), "idle": _vehicle(vehicle_id="idle", fixed_cost=75)}
    evaluations = evaluate_fleet({"used": [0, 1], "idle": []}, {"used": [Job("A", 0, 1, 0)]}, vehicles, dur, dist, datetime(2026, 1, 1), {"used": (None, None), "idle": (None, None)}, service_time_per_stop_s=0)
    assert evaluations["idle"].fixed_vehicle_cost == 0
    assert fleet_total_cost(evaluations) == evaluations["used"].total_cost


def test_default_weather_and_traffic_are_neutral():
    dur, dist = _matrices(2)
    result = evaluate_route([0, 1], [Job("A", 0, 1, 0)], _vehicle(), dur, dist, datetime(2026, 1, 1), service_time_per_stop_s=0)
    leg = result.legs[0]
    assert leg.weather_factor == leg.traffic_factor == 1.0


def test_existing_single_vehicle_solver_contract_remains_compatible():
    from src.optimizer.fleet import FleetVehicle, evaluate_route as legacy_evaluate_route

    dur, dist = _matrices(2)
    metrics = legacy_evaluate_route([0, 1], [Job("A", 0, 1, 100)], FleetVehicle("v", capacity_kg=500), dur, dist)
    assert metrics.peak_load_kg == 100
