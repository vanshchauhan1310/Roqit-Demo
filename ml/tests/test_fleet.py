"""Tests for the multi-vehicle fleet solver.

Runs standalone (`python tests/test_fleet.py` from ml/) or under pytest - the
project has no pytest config, so plain asserts + a __main__ runner keep this
usable either way.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.optimizer import opt  # noqa: E402
from src.optimizer.fleet import (  # noqa: E402
    CostRates,
    FleetVehicle,
    _hub_pickup_priority,
    evaluate_route,
    fleet_solve,
)


def _grid_matrices(n: int, leg_seconds: float = 600.0, leg_meters: float = 20000.0):
    """Uniform matrices: every hop costs the same, so any cost difference between
    solutions comes from the number of legs and the load carried, not geography."""
    dur = [[0.0 if i == j else leg_seconds for j in range(n)] for i in range(n)]
    dist = [[0.0 if i == j else leg_meters for j in range(n)] for i in range(n)]
    return dur, dist


def test_single_vehicle_takes_everything_when_capacity_allows():
    jobs = [
        opt.Job(trip_id="A", pickup_idx=0, delivery_idx=1, load_weight_kg=400),
        opt.Job(trip_id="B", pickup_idx=2, delivery_idx=3, load_weight_kg=300),
    ]
    dur, dist = _grid_matrices(4)
    vehicles = [FleetVehicle(vehicle_id="V1", capacity_kg=5000)]

    sol = fleet_solve(jobs, vehicles, dur, dist, seed=1)

    assert sol.feasible
    assert not sol.unassigned_trip_ids
    assert sol.vehicles_used == 1
    assert sorted(sol.routes[0].trip_ids) == ["A", "B"]
    print("PASS single vehicle takes everything")


def test_initial_construction_orders_pickups_from_the_nearest_compatible_hub():
    """Hub proximity is the first construction signal; vehicle compatibility still applies."""
    # nodes: job A pickup/drop, job B pickup/drop, hub A, hub B
    jobs = [
        opt.Job("A", 0, 1, 100, allowed_vehicle_ids=frozenset({"V1"})),
        opt.Job("B", 2, 3, 100, allowed_vehicle_ids=frozenset({"V2"})),
    ]
    _, dist = _grid_matrices(6, leg_meters=100_000)
    dist[4][0] = 1_000
    dist[5][2] = 2_000
    vehicles = [FleetVehicle("V1", start_idx=4), FleetVehicle("V2", start_idx=5)]

    assert [job.trip_id for job in sorted(jobs, key=lambda job: _hub_pickup_priority(job, vehicles, dist))] == ["A", "B"]
    print("PASS pickup construction is ordered from compatible hubs")


def test_capacity_forces_split_across_two_vehicles():
    """Two 900kg jobs, each vehicle caps at 1000kg. They cannot share a vehicle
    if carried concurrently, and with only 4 stops the solver must use both."""
    jobs = [
        opt.Job(trip_id="A", pickup_idx=0, delivery_idx=1, load_weight_kg=900),
        opt.Job(trip_id="B", pickup_idx=2, delivery_idx=3, load_weight_kg=900),
    ]
    dur, dist = _grid_matrices(4)
    vehicles = [
        FleetVehicle(vehicle_id="V1", capacity_kg=1000),
        FleetVehicle(vehicle_id="V2", capacity_kg=1000),
    ]

    sol = fleet_solve(jobs, vehicles, dur, dist, seed=1)

    assert sol.feasible
    assert not sol.unassigned_trip_ids
    # Both jobs placed; each vehicle's peak load must respect its cap.
    for r in sol.routes:
        assert r.metrics.peak_load_kg <= 1000 + 1e-9
    assert sum(len(r.trip_ids) for r in sol.routes) == 2
    print("PASS capacity split across vehicles")


def test_split_parts_preserve_full_parent_weight_and_vehicle_assignments():
    """A split uses assignment weights, never a reduced parent trip weight.
    Each part remains a pickup->delivery job and is restricted to its allocated
    truck, so the solver cannot collapse the two parts onto one vehicle."""
    jobs = [
        opt.Job("PARENT part 1/2", 0, 1, 18_000, parent_trip_id="PARENT", original_load_weight_kg=25_000, allowed_vehicle_ids=frozenset({"V1"})),
        opt.Job("PARENT part 2/2", 2, 3, 7_000, parent_trip_id="PARENT", original_load_weight_kg=25_000, allowed_vehicle_ids=frozenset({"V2"})),
    ]
    dur, dist = _grid_matrices(4)
    vehicles = [
        FleetVehicle(vehicle_id="V1", capacity_kg=23_895),
        FleetVehicle(vehicle_id="V2", capacity_kg=7_913),
    ]

    sol = fleet_solve(jobs, vehicles, dur, dist, seed=1)

    assert sol.feasible
    assert sum(job.load_weight_kg for job in jobs if job.parent_trip_id == "PARENT") == 25_000
    by_vehicle = {route.vehicle_id: route for route in sol.routes}
    assert by_vehicle["V1"].trip_ids == ["PARENT part 1/2"]
    assert by_vehicle["V2"].trip_ids == ["PARENT part 2/2"]
    assert by_vehicle["V1"].metrics.peak_load_kg <= 23_895
    assert by_vehicle["V2"].metrics.peak_load_kg <= 7_913
    print("PASS split cargo preserves parent total across allocated vehicles")


def test_sequential_service_fits_where_concurrent_would_not():
    """A=800 + B=700 vs a 1144kg truck: infeasible if both are aboard at once,
    feasible pickup->drop->pickup->drop. The solver must find the sequential
    order rather than declaring it unassignable - the exact case from the audit."""
    jobs = [
        opt.Job(trip_id="A", pickup_idx=0, delivery_idx=1, load_weight_kg=800),
        opt.Job(trip_id="B", pickup_idx=2, delivery_idx=3, load_weight_kg=700),
    ]
    dur, dist = _grid_matrices(4)
    vehicles = [FleetVehicle(vehicle_id="V1", capacity_kg=1144)]

    sol = fleet_solve(jobs, vehicles, dur, dist, seed=7)

    assert not sol.unassigned_trip_ids, "both trips should fit sequentially on one 1144kg vehicle"
    assert sol.feasible
    used = [r for r in sol.routes if r.route]
    assert len(used) == 1
    assert used[0].metrics.peak_load_kg <= 1144 + 1e-9
    assert used[0].metrics.peak_load_kg == 800, "peak should be the heavier trip alone, not 1500"
    print("PASS sequential service beats concurrent-load rejection")


def test_job_heavier_than_every_vehicle_is_unassigned_not_forced():
    jobs = [
        opt.Job(trip_id="OK", pickup_idx=0, delivery_idx=1, load_weight_kg=500),
        opt.Job(trip_id="TOOBIG", pickup_idx=2, delivery_idx=3, load_weight_kg=9999),
    ]
    dur, dist = _grid_matrices(4)
    vehicles = [FleetVehicle(vehicle_id="V1", capacity_kg=1000)]

    sol = fleet_solve(jobs, vehicles, dur, dist, seed=1)

    assert sol.unassigned_trip_ids == ["TOOBIG"]
    assert sol.feasible, "remaining routes must still be valid"
    assert sol.routes[0].trip_ids == ["OK"]
    print("PASS oversized job reported unassigned, not force-fitted")


def test_empty_infeasible_fleet_does_not_claim_a_monetary_total():
    jobs = [opt.Job(trip_id="TOOBIG", pickup_idx=0, delivery_idx=1, load_weight_kg=9_999)]
    dur, dist = _grid_matrices(2)

    solution = fleet_solve(jobs, [FleetVehicle(vehicle_id="V1", capacity_kg=1_000)], dur, dist, seed=1)

    assert not solution.feasible
    assert solution.unassigned_trip_ids == ["TOOBIG"]
    assert not solution.totals.cost_is_monetary
    print("PASS empty infeasible fleet has no monetary total")


def test_fixed_cost_discourages_using_extra_vehicles():
    """With ample capacity everywhere, a per-vehicle fixed cost should keep the
    solver from spreading jobs across trucks it doesn't need."""
    jobs = [
        opt.Job(trip_id="A", pickup_idx=0, delivery_idx=1, load_weight_kg=100),
        opt.Job(trip_id="B", pickup_idx=2, delivery_idx=3, load_weight_kg=100),
    ]
    dur, dist = _grid_matrices(4)
    vehicles = [
        FleetVehicle(vehicle_id="V1", capacity_kg=10000, fixed_cost=100000),
        FleetVehicle(vehicle_id="V2", capacity_kg=10000, fixed_cost=100000),
    ]

    sol = fleet_solve(jobs, vehicles, dur, dist, seed=3)

    assert sol.vehicles_used == 1, "a large fixed cost should consolidate onto one vehicle"
    print("PASS fixed cost prevents unnecessary vehicle use")


def test_hard_constraints_hold_precedence_and_capacity():
    jobs = [
        opt.Job(trip_id="A", pickup_idx=0, delivery_idx=1, load_weight_kg=600),
        opt.Job(trip_id="B", pickup_idx=2, delivery_idx=3, load_weight_kg=600),
        opt.Job(trip_id="C", pickup_idx=4, delivery_idx=5, load_weight_kg=600),
    ]
    dur, dist = _grid_matrices(6)
    vehicles = [FleetVehicle(vehicle_id="V1", capacity_kg=1300), FleetVehicle(vehicle_id="V2", capacity_kg=1300)]

    sol = fleet_solve(jobs, vehicles, dur, dist, seed=11)

    for r in sol.routes:
        if not r.route:
            continue
        vjobs = [j for j in jobs if j.trip_id in r.trip_ids]
        cap = next(v.capacity_kg for v in vehicles if v.vehicle_id == r.vehicle_id)
        assert opt.route_is_feasible(r.route, vjobs, cap), "solver returned an infeasible route"
        pos = {stop: i for i, stop in enumerate(r.route)}
        for j in vjobs:
            assert pos[j.pickup_idx] < pos[j.delivery_idx], "delivery preceded its own pickup"
    print("PASS precedence and capacity hold on every returned route")


def test_depot_legs_add_distance():
    jobs = [opt.Job(trip_id="A", pickup_idx=1, delivery_idx=2, load_weight_kg=100)]
    dur, dist = _grid_matrices(4)
    open_route = FleetVehicle(vehicle_id="V1", capacity_kg=5000)
    with_depot = FleetVehicle(vehicle_id="V2", capacity_kg=5000, start_idx=0, end_idx=0)

    m_open = evaluate_route([1, 2], jobs, open_route, dur, dist)
    m_depot = evaluate_route([1, 2], jobs, with_depot, dur, dist)

    assert m_depot.distance_meters > m_open.distance_meters
    assert m_depot.distance_meters == m_open.distance_meters + 2 * 20000.0
    print("PASS depot start/end legs are counted")


def test_hub_round_trip_duration_limit_is_a_hard_constraint():
    """The limit includes Hub->pickup and delivery->Hub, not just work stops."""
    jobs = [opt.Job(trip_id="A", pickup_idx=1, delivery_idx=2, load_weight_kg=100)]
    dur, dist = _grid_matrices(4, leg_seconds=3_600)
    vehicle = FleetVehicle(
        vehicle_id="V1", capacity_kg=5_000, start_idx=0, end_idx=0,
        max_route_duration_seconds=10_000,  # full route is 3 legs / 10,800 s
    )

    solution = fleet_solve(jobs, [vehicle], dur, dist, seed=1)

    assert not solution.feasible
    assert solution.unassigned_trip_ids == ["A"]
    print("PASS hub-inclusive route-duration limit prevents impractical dispatch")


def test_fleet_peak_is_the_highest_route_peak_not_a_sum():
    jobs = [
        opt.Job(trip_id="A", pickup_idx=0, delivery_idx=1, load_weight_kg=600),
        opt.Job(trip_id="B", pickup_idx=2, delivery_idx=3, load_weight_kg=400),
    ]
    dur, dist = _grid_matrices(4)
    vehicles = [
        FleetVehicle("V1", capacity_kg=600, fixed_cost=1),
        FleetVehicle("V2", capacity_kg=400, fixed_cost=1),
    ]

    solution = fleet_solve(jobs, vehicles, dur, dist, seed=1)
    active_peaks = [route.metrics.peak_load_kg for route in solution.routes if route.route]

    assert solution.feasible
    assert solution.totals.peak_load_kg == max(active_peaks)
    print("PASS fleet peak reconciles as the maximum route peak")


def test_two_vehicles_win_when_their_total_cost_is_lower_than_one():
    """Vehicle count must never be an objective: the 2-truck plan is selected
    when it costs less than serving both jobs with either truck alone."""
    jobs = [
        opt.Job(trip_id="A", pickup_idx=0, delivery_idx=1, load_weight_kg=100),
        opt.Job(trip_id="B", pickup_idx=2, delivery_idx=3, load_weight_kg=100),
    ]
    n = 6  # A pickup/drop, B pickup/drop, hub A, hub B
    dur = [[0.0 for _ in range(n)] for _ in range(n)]
    dist = [[0.0 if i == j else 100_000.0 for j in range(n)] for i in range(n)]
    # Each hub is close to its own trip, while crossing to the other trip is costly.
    for i, j in ((4, 0), (0, 1), (1, 4), (5, 2), (2, 3), (3, 5)):
        dist[i][j] = 1_000.0
    vehicles = [
        FleetVehicle("V1", capacity_kg=5_000, start_idx=4, end_idx=4, cost_per_km=1.0),
        FleetVehicle("V2", capacity_kg=5_000, start_idx=5, end_idx=5, cost_per_km=1.0),
    ]

    sol = fleet_solve(jobs, vehicles, dur, dist, seed=1)

    assert sol.feasible
    assert sol.vehicles_used == 2
    assert sol.totals.total_cost == 6.0
    print("PASS lower-cost two-vehicle fleet beats one-vehicle plan")


def test_nearer_hub_is_preferred_when_all_other_costs_match():
    jobs = [opt.Job(trip_id="A", pickup_idx=0, delivery_idx=1, load_weight_kg=100)]
    n = 4  # pickup/drop, near hub, far hub
    dur = [[0.0 for _ in range(n)] for _ in range(n)]
    dist = [[0.0 if i == j else 50_000.0 for j in range(n)] for i in range(n)]
    for i, j in ((2, 0), (0, 1), (1, 2)):
        dist[i][j] = 1_000.0
    vehicles = [
        FleetVehicle("near", capacity_kg=5_000, start_idx=2, end_idx=2, cost_per_km=1.0),
        FleetVehicle("far", capacity_kg=5_000, start_idx=3, end_idx=3, cost_per_km=1.0),
    ]

    sol = fleet_solve(jobs, vehicles, dur, dist, seed=1)

    assert sol.vehicles_used == 1
    assert next(route.vehicle_id for route in sol.routes if route.route) == "near"
    print("PASS nearer hub wins through lower total route cost")


def test_cost_is_monetary_only_when_rates_supplied():
    jobs = [opt.Job(trip_id="A", pickup_idx=0, delivery_idx=1, load_weight_kg=1000)]
    dur, dist = _grid_matrices(2)

    bare = evaluate_route([0, 1], jobs, FleetVehicle("V1", capacity_kg=5000), dur, dist)
    assert not bare.cost_is_monetary, "no fuel data and no rates should flag a non-monetary proxy"
    assert bare.total_cost == bare.duration_seconds

    priced = evaluate_route(
        [0, 1], jobs,
        FleetVehicle("V1", capacity_kg=5000, avg_kmpl_rated=10.0, fuel_price_per_l=100.0),
        dur, dist,
        rates=CostRates(driver_cost_per_hour=200.0, operating_cost_per_km=12.0),
    )
    assert priced.cost_is_monetary
    assert priced.fuel_liters > 0 and priced.fuel_cost > 0
    assert priced.driver_cost > 0 and priced.operating_cost > 0
    print("PASS monetary vs proxy cost correctly distinguished")


def test_heavier_load_burns_more_fuel_on_the_same_leg():
    """Load must influence fuel through the derated-mileage model, not be a
    separate additive penalty."""
    dur, dist = _grid_matrices(2)
    v = FleetVehicle("V1", capacity_kg=20000, avg_kmpl_rated=10.0, fuel_price_per_l=100.0)

    light = evaluate_route([0, 1], [opt.Job("L", 0, 1, 100)], v, dur, dist)
    heavy = evaluate_route([0, 1], [opt.Job("H", 0, 1, 10000)], v, dur, dist)

    assert heavy.fuel_liters > light.fuel_liters
    assert heavy.distance_meters == light.distance_meters, "same distance, different fuel"
    print("PASS load-dependent fuel responds to cargo weight")


def test_vehicles_at_different_hubs_use_their_own_hub():
    """V1 is based at hub H1 (near job A), V2 at hub H2 (near job B). Each
    vehicle's route must start and end at ITS OWN hub, and the cheap assignment
    is the one where each serves the job near its own base."""
    # nodes: 0,1 = A pickup/drop | 2,3 = B pickup/drop | 4 = H1 | 5 = H2
    n = 6
    FAR, NEAR = 100000.0, 1000.0  # metres
    dist = [[0.0] * n for _ in range(n)]
    a_cluster, b_cluster = {0, 1, 4}, {2, 3, 5}
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            same = (i in a_cluster and j in a_cluster) or (i in b_cluster and j in b_cluster)
            dist[i][j] = NEAR if same else FAR
    dur = [[d / 10.0 for d in row] for row in dist]

    jobs = [
        opt.Job(trip_id="A", pickup_idx=0, delivery_idx=1, load_weight_kg=100),
        opt.Job(trip_id="B", pickup_idx=2, delivery_idx=3, load_weight_kg=100),
    ]
    vehicles = [
        FleetVehicle("V1", capacity_kg=5000, start_idx=4, end_idx=4),
        FleetVehicle("V2", capacity_kg=5000, start_idx=5, end_idx=5),
    ]

    sol = fleet_solve(jobs, vehicles, dur, dist, seed=2)
    by_v = {r.vehicle_id: r for r in sol.routes}

    assert by_v["V1"].trip_ids == ["A"], "V1 (hub H1) should take the job near H1"
    assert by_v["V2"].trip_ids == ["B"], "V2 (hub H2) should take the job near H2"

    # each route's full sequence is bracketed by its OWN hub
    assert by_v["V1"].full_sequence(vehicles[0])[0] == 4
    assert by_v["V1"].full_sequence(vehicles[0])[-1] == 4
    assert by_v["V2"].full_sequence(vehicles[1])[0] == 5
    assert by_v["V2"].full_sequence(vehicles[1])[-1] == 5
    print("PASS vehicles route from their own distinct hubs")


def test_driver_cost_scales_with_route_duration():
    jobs = [opt.Job(trip_id="A", pickup_idx=0, delivery_idx=1, load_weight_kg=100)]
    v = FleetVehicle("V1", capacity_kg=5000)
    rates = CostRates(driver_cost_per_hour=150.0)

    short_dur, dist = _grid_matrices(2, leg_seconds=3600.0)  # 1 h
    long_dur, _ = _grid_matrices(2, leg_seconds=7200.0)  # 2 h

    m_short = evaluate_route([0, 1], jobs, v, short_dur, dist, rates=rates)
    m_long = evaluate_route([0, 1], jobs, v, long_dur, dist, rates=rates)

    assert m_short.driver_cost > 150.0, "loaded travel must include the utilization speed derate"
    assert abs(m_long.driver_cost - 2 * m_short.driver_cost) < 1e-6, "doubling duration must double driver cost"
    print("PASS driver cost scales with duration")


def test_operating_cost_scales_with_distance():
    jobs = [opt.Job(trip_id="A", pickup_idx=0, delivery_idx=1, load_weight_kg=100)]
    v = FleetVehicle("V1", capacity_kg=5000)
    rates = CostRates(operating_cost_per_km=8.0)

    dur, short_dist = _grid_matrices(2, leg_meters=10000.0)  # 10 km
    _, long_dist = _grid_matrices(2, leg_meters=30000.0)  # 30 km

    m_short = evaluate_route([0, 1], jobs, v, dur, short_dist, rates=rates)
    m_long = evaluate_route([0, 1], jobs, v, dur, long_dist, rates=rates)

    assert abs(m_short.operating_cost - 80.0) < 1e-6
    assert abs(m_long.operating_cost - 240.0) < 1e-6
    print("PASS per-km operating cost scales with distance")


def test_full_rate_set_marks_cost_monetary_and_sums_components():
    jobs = [opt.Job(trip_id="A", pickup_idx=0, delivery_idx=1, load_weight_kg=1000)]
    dur, dist = _grid_matrices(2, leg_seconds=3600.0, leg_meters=20000.0)
    v = FleetVehicle("V1", capacity_kg=5000, avg_kmpl_rated=12.0, fuel_price_per_l=100.0, fixed_cost=400.0)
    rates = CostRates(driver_cost_per_hour=150.0, operating_cost_per_km=8.0)

    m = evaluate_route([0, 1], jobs, v, dur, dist, rates=rates)

    assert m.cost_is_monetary
    expected = m.fuel_cost + m.driver_cost + m.operating_cost + m.fixed_cost
    assert abs(m.total_cost - expected) < 1e-6, "total must be the sum of its costed components"
    assert m.fixed_cost == 400.0 and m.driver_cost > 150.0 and m.operating_cost == 160.0
    print("PASS full rate set produces a monetary, component-summed cost")


def test_optimizer_leaves_a_third_vehicle_idle_when_two_suffice():
    """Three vehicles offered, all feasible; fixed costs should keep the solver
    from activating one it doesn't need."""
    jobs = [
        opt.Job(trip_id="A", pickup_idx=0, delivery_idx=1, load_weight_kg=800),
        opt.Job(trip_id="B", pickup_idx=2, delivery_idx=3, load_weight_kg=700),
        opt.Job(trip_id="C", pickup_idx=4, delivery_idx=5, load_weight_kg=300),
        opt.Job(trip_id="D", pickup_idx=6, delivery_idx=7, load_weight_kg=1500),
    ]
    dur, dist = _grid_matrices(8)
    vehicles = [
        FleetVehicle("V1", capacity_kg=1144, avg_kmpl_rated=12, fuel_price_per_l=100, fixed_cost=400),
        FleetVehicle("V2", capacity_kg=3500, avg_kmpl_rated=7, fuel_price_per_l=100, fixed_cost=800),
        FleetVehicle("V3", capacity_kg=5000, avg_kmpl_rated=6, fuel_price_per_l=100, fixed_cost=1200),
    ]

    sol = fleet_solve(jobs, vehicles, dur, dist, seed=5)

    assert not sol.unassigned_trip_ids
    assert sol.vehicles_used < 3, "the third vehicle should stay idle when two can cover the work"
    idle = [r.vehicle_id for r in sol.routes if not r.route]
    assert idle, "at least one vehicle must remain idle when two suffice"
    print(f"PASS one vehicle left idle (used {sol.vehicles_used}/3, idle: {idle})")


def test_each_vehicle_is_costed_at_its_own_rates():
    """A mixed fleet must charge each vehicle its own per-km and driver rate -
    one shared pair would misprice every vehicle but one."""
    jobs = [opt.Job(trip_id="A", pickup_idx=0, delivery_idx=1, load_weight_kg=100)]
    dur, dist = _grid_matrices(2, leg_seconds=3600.0, leg_meters=10000.0)  # 1 h, 10 km

    cheap = FleetVehicle("V1", capacity_kg=5000, cost_per_km=8.0, driver_cost_per_hour=150.0)
    dear = FleetVehicle("V2", capacity_kg=5000, cost_per_km=15.0, driver_cost_per_hour=180.0)

    m_cheap = evaluate_route([0, 1], jobs, cheap, dur, dist)
    m_dear = evaluate_route([0, 1], jobs, dear, dur, dist)

    assert abs(m_cheap.operating_cost - 80.0) < 1e-6
    assert abs(m_dear.operating_cost - 150.0) < 1e-6
    assert abs(m_cheap.driver_cost / 150.0 - m_dear.driver_cost / 180.0) < 1e-6
    print("PASS each vehicle costed at its own per-km and driver rate")


def test_fleet_total_stays_monetary_when_an_idle_vehicle_is_listed_last():
    """Idle vehicles have zero/proxy metrics and must not downgrade a priced fleet total."""
    jobs = [opt.Job(trip_id="A", pickup_idx=0, delivery_idx=1, load_weight_kg=100)]
    dur, dist = _grid_matrices(2, leg_seconds=3600.0, leg_meters=10_000.0)
    vehicles = [
        FleetVehicle("priced", capacity_kg=5_000, cost_per_km=8.0),
        FleetVehicle("idle", capacity_kg=5_000),
    ]

    solution = fleet_solve(jobs, vehicles, dur, dist, seed=1)

    assert solution.totals.cost_is_monetary
    assert solution.totals.total_cost == 80.0
    print("PASS idle vehicle does not downgrade fleet monetary total")


def test_incompatible_high_capacity_vehicle_cannot_make_a_job_look_servable():
    """Compatibility applies before the capacity feasibility shortcut."""
    jobs = [
        opt.Job("A", 0, 1, 900, allowed_vehicle_ids=frozenset({"small"})),
    ]
    dur, dist = _grid_matrices(2)
    vehicles = [
        FleetVehicle("small", capacity_kg=500),
        FleetVehicle("large", capacity_kg=5_000),
    ]

    solution = fleet_solve(jobs, vehicles, dur, dist, seed=1)

    assert not solution.feasible
    assert solution.unassigned_trip_ids == ["A"]
    print("PASS incompatible capacity is not treated as feasible")


def test_per_vehicle_rate_overrides_fleet_wide_fallback():
    jobs = [opt.Job(trip_id="A", pickup_idx=0, delivery_idx=1, load_weight_kg=100)]
    dur, dist = _grid_matrices(2, leg_seconds=3600.0, leg_meters=10000.0)
    fallback = CostRates(driver_cost_per_hour=100.0, operating_cost_per_km=5.0)

    override = FleetVehicle("V1", capacity_kg=5000, cost_per_km=20.0, driver_cost_per_hour=300.0)
    inherits = FleetVehicle("V2", capacity_kg=5000)

    m_override = evaluate_route([0, 1], jobs, override, dur, dist, rates=fallback)
    m_inherits = evaluate_route([0, 1], jobs, inherits, dur, dist, rates=fallback)

    assert abs(m_override.operating_cost - 200.0) < 1e-6, "per-vehicle rate must win"
    assert m_override.driver_cost > 300.0
    assert abs(m_inherits.operating_cost - 50.0) < 1e-6, "no per-vehicle rate falls back to fleet-wide"
    assert abs(m_override.driver_cost / 300.0 - m_inherits.driver_cost / 100.0) < 1e-6
    print("PASS per-vehicle rates override the fleet-wide fallback")


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    for t in TESTS:
        t()
    print(f"\n{len(TESTS)} tests passed.")
