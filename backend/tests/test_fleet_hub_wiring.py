"""Tests for the backend side of fleet optimization: hub->matrix index mapping
and cost-rate completeness.

These cover the pure logic only - no DB session required. Runs standalone
(`python tests/test_fleet_hub_wiring.py` from backend/) or under pytest.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.schemas.optimize import OptimizeStopInput  # noqa: E402
from app.services.dispatch_config_service import ResolvedVehicleConfig  # noqa: E402
from app.services.route_optimizer import (  # noqa: E402
    _unweighed_trip_ids,
    build_hub_nodes,
)


def _hub(hub_id: str, lat: float, lon: float):
    return SimpleNamespace(hub_id=hub_id, latitude=lat, longitude=lon)


def _stops():
    return [
        OptimizeStopInput(key="a:p", latitude=17.0, longitude=78.0, trip_id="A", stop_type="pickup", load_weight_kg=800),
        OptimizeStopInput(key="a:d", latitude=17.1, longitude=78.1, trip_id="A", stop_type="delivery"),
        OptimizeStopInput(key="b:p", latitude=17.2, longitude=78.2, trip_id="B", stop_type="pickup", load_weight_kg=700),
        OptimizeStopInput(key="b:d", latitude=17.3, longitude=78.3, trip_id="B", stop_type="delivery"),
    ]


def test_hub_nodes_are_appended_after_stops():
    """Job indices reference stop positions, so hubs must never be inserted
    before or among them - only appended."""
    stops = _stops()
    configs = [
        ResolvedVehicleConfig(vehicle_id="V1", start_hub=_hub("h1", 17.5, 78.5), end_hub=_hub("h1", 17.5, 78.5)),
    ]
    points, per_vehicle = build_hub_nodes(stops, configs)

    assert len(points) == 5, "4 stops + 1 distinct hub"
    assert points[:4] == [(17.0, 78.0), (17.1, 78.1), (17.2, 78.2), (17.3, 78.3)]
    assert points[4] == (17.5, 78.5)
    assert per_vehicle["V1"] == (4, 4), "same hub for start and end shares one node index"
    print("PASS hub nodes appended after stops, stop indices undisturbed")


def test_distinct_hubs_get_distinct_indices_and_are_deduped():
    stops = _stops()
    h1, h2 = _hub("h1", 17.5, 78.5), _hub("h2", 18.9, 79.9)
    configs = [
        ResolvedVehicleConfig(vehicle_id="V1", start_hub=h1, end_hub=h1),
        ResolvedVehicleConfig(vehicle_id="V2", start_hub=h2, end_hub=h2),
        ResolvedVehicleConfig(vehicle_id="V3", start_hub=h1, end_hub=h1),  # shares V1's hub
    ]
    points, per_vehicle = build_hub_nodes(stops, configs)

    assert len(points) == 6, "4 stops + 2 distinct hubs (h1 reused by V3, not duplicated)"
    assert per_vehicle["V1"] == (4, 4)
    assert per_vehicle["V2"] == (5, 5)
    assert per_vehicle["V3"] == (4, 4), "a shared hub must resolve to the same node index"
    print("PASS distinct hubs indexed separately, shared hubs deduplicated")


def test_separate_start_and_end_hubs():
    stops = _stops()
    configs = [
        ResolvedVehicleConfig(vehicle_id="V1", start_hub=_hub("h1", 17.5, 78.5), end_hub=_hub("h2", 18.9, 79.9)),
    ]
    points, per_vehicle = build_hub_nodes(stops, configs)

    assert len(points) == 6
    assert per_vehicle["V1"] == (4, 5), "start and end hubs are different nodes"
    print("PASS separate start/end hubs map to separate indices")


def test_vehicle_without_hub_gets_no_indices():
    stops = _stops()
    configs = [ResolvedVehicleConfig(vehicle_id="V1")]
    points, per_vehicle = build_hub_nodes(stops, configs)

    assert len(points) == 4, "no hub configured => no extra nodes"
    assert per_vehicle["V1"] == (None, None), "open route, matching single-vehicle behavior"
    print("PASS hub-less vehicle produces an open route")


def test_unknown_weight_is_not_zero_weight():
    stops = [
        OptimizeStopInput(key="a:p", latitude=1, longitude=1, trip_id="A", stop_type="pickup", load_weight_kg=800),
        OptimizeStopInput(key="b:p", latitude=2, longitude=2, trip_id="B", stop_type="pickup", load_weight_kg=None),
        OptimizeStopInput(key="c:p", latitude=3, longitude=3, trip_id="C", stop_type="pickup", load_weight_kg=0.0),
    ]
    assert _unweighed_trip_ids(stops) == ["B"], "0.0 kg is a recorded weight; only None is unknown"
    print("PASS unknown weight distinguished from a recorded 0 kg")


def test_cost_completeness_requires_every_rate():
    full = ResolvedVehicleConfig(
        vehicle_id="V1", capacity_kg=1144, avg_kmpl_rated=12.0,
        fuel_price_per_l=100.0, fixed_route_cost=400.0, cost_per_km=8.0,
    )
    assert full.can_cost_fuel and full.is_fully_costed

    for field, value in [("fuel_price_per_l", None), ("cost_per_km", None), ("fixed_route_cost", None)]:
        partial = ResolvedVehicleConfig(
            vehicle_id="V1", capacity_kg=1144, avg_kmpl_rated=12.0,
            fuel_price_per_l=100.0, fixed_route_cost=400.0, cost_per_km=8.0,
        )
        setattr(partial, field, value)
        assert not partial.is_fully_costed, f"missing {field} must block a monetary claim"

    # A rate of zero is a real business statement, not a missing one.
    zeroed = ResolvedVehicleConfig(
        vehicle_id="V1", capacity_kg=1144, avg_kmpl_rated=12.0,
        fuel_price_per_l=100.0, fixed_route_cost=0.0, cost_per_km=0.0,
    )
    assert zeroed.is_fully_costed, "0.0 is a configured rate and must count as known"
    print("PASS cost completeness distinguishes an absent rate from a zero rate")


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    for t in TESTS:
        t()
    print(f"\n{len(TESTS)} tests passed.")
