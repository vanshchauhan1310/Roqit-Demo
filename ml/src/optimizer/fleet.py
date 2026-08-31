"""Multi-vehicle fleet solver - assigns pickup/delivery jobs across a fleet AND
sequences each vehicle's stops, minimizing total fleet operating cost.

Relationship to opt.py: this module owns the *assignment* decision (which vehicle
serves which trip) and the fleet-level cost objective; opt.py owns the
single-route primitives (feasibility, load-at-position, pair insertion) which are
reused here unchanged. Nothing in opt.py or hybrid_solver.py is modified - the
existing single-vehicle path stays byte-for-byte identical.

WHAT IS AND ISN'T MODELED HERE
------------------------------
Modeled, from data that actually exists in this app:
  - per-stop cumulative load and vehicle capacity (hard constraint, via opt.py)
  - pickup-before-delivery precedence (hard constraint, via opt.py)
  - load-derated fuel consumption and fuel cost
  - optional driver-time and per-km operating cost
  - optional per-vehicle fixed cost, so adding a vehicle must EARN its place
  - optional depot/hub start+end legs per vehicle

Deliberately NOT modeled, because the underlying data source does not exist yet
(see MULTI_VEHICLE_ROUTING.md): time-bucketed traffic factors, per-segment road
classification, forecast weather at expected arrival time, driver shift windows,
cargo type / hazmat / refrigeration / volume. Rather than hard-code invented
multipliers for these, `leg_duration_factor` below is a neutral-by-default hook
that a caller can supply once real data is available. A factor of 1.0 - the
default - means "no adjustment", not "no traffic".
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from itertools import combinations
from typing import Callable

from src.optimizer import opt
from src.optimizer.opt import Job, Matrix


# Debug/diagnostic structures
@dataclass
class InsertionAttempt:
    """Records a single insertion attempt for debugging."""
    vehicle_id: str
    pickup_position: int
    delivery_position: int
    feasible: bool
    failure_reason: str | None
    peak_load_after: float
    incremental_cost: float | None


@dataclass
class VehicleInsertionDiagnostic:
    """Aggregated diagnostics for one vehicle's insertion attempts."""
    vehicle_id: str
    vehicle_capacity_kg: float | None
    current_peak_load_kg: float
    static_remaining_capacity_kg: float | None
    trip_weight_kg: float
    total_pickup_positions_tested: int
    total_delivery_positions_tested: int
    capacity_failures: int
    precedence_failures: int
    feasible_insertions: int
    best_peak_load_kg: float | None
    best_incremental_cost: float | None
    best_pickup_position: int | None
    best_delivery_position: int | None


@dataclass
class TripAssignmentDiagnostic:
    """Complete diagnostic for a trip's assignment attempt."""
    trip_id: str
    trip_weight_kg: float
    vehicle_diagnostics: list[VehicleInsertionDiagnostic]
    assigned_vehicle_id: str | None
    assigned_pickup_position: int | None
    assigned_delivery_position: int | None
    assigned_peak_load_kg: float | None
    assigned_incremental_cost: float | None
    status: str  # "ASSIGNED", "UNASSIGNED", "EXCEEDS_ALL_VEHICLES"
    minimum_required_capacity_kg: float | None
    # Additional failure reason details
    primary_failure_reason: str | None = None
    capacity_failures: int = 0
    precedence_failures: int = 0
    time_window_failures: int = 0
    vehicle_incompatible_failures: int = 0
    total_positions_tested: int = 0


def _load_at_positions_with_depot(
    route: list[int],
    jobs: list[Job],
    vehicle: FleetVehicle,
) -> list[float]:
    """Cumulative load including depot legs."""
    if not route:
        return []
    
    # Get loads at each position in the route (excluding depot)
    loads = opt._load_at_positions(route, jobs)
    
    result = []
    if vehicle.start_idx is not None:
        result.append(0.0)  # depot start - empty
    result.extend(loads)
    if vehicle.end_idx is not None:
        # On return to depot, vehicle should be empty (all deliveries done)
        result.append(0.0)
    
    return result


def _try_insert_with_diagnostics(
    route: list[int],
    placed: list[Job],
    job: Job,
    vehicle: FleetVehicle,
    duration_matrix: Matrix,
    distance_matrix: Matrix,
    rates: CostRates | None,
    leg_duration_factor: LegDurationFactor | None,
    debug: bool = False,
) -> tuple[list[InsertionAttempt] | None, tuple[list[int], float] | None]:
    """Try inserting a job with optional diagnostic collection."""
    attempts = [] if debug else None
    
    if not route:
        candidate = [job.pickup_idx, job.delivery_idx]
        feasible = _candidate_feasible(candidate, [job], vehicle, duration_matrix, distance_matrix, rates, leg_duration_factor)
        if debug:
            peak = job.load_weight_kg if feasible else float('inf')
            attempts.append(InsertionAttempt(
                vehicle_id=vehicle.vehicle_id,
                pickup_position=0,
                delivery_position=0,
                feasible=feasible,
                failure_reason="CAPACITY" if not feasible else None,
                peak_load_after=peak,
                incremental_cost=evaluate_route(candidate, [job], vehicle, duration_matrix, distance_matrix, rates, leg_duration_factor).total_cost if feasible else None,
            ))
        if not feasible:
            return attempts, None
        cost = evaluate_route(candidate, [job], vehicle, duration_matrix, distance_matrix, rates, leg_duration_factor).total_cost
        return attempts, (candidate, cost)

    all_jobs = placed + [job]
    base = evaluate_route(route, placed, vehicle, duration_matrix, distance_matrix, rates, leg_duration_factor).total_cost

    best: tuple[list[int], float] | None = None
    n = len(route)
    for pickup_pos in range(n + 1):
        for delivery_pos in range(pickup_pos, n + 1):
            candidate = opt.insert_pair(route, job, pickup_pos, delivery_pos)
            feasible = _candidate_feasible(candidate, all_jobs, vehicle, duration_matrix, distance_matrix, rates, leg_duration_factor)
            
            if debug:
                if feasible:
                    cost = evaluate_route(candidate, all_jobs, vehicle, duration_matrix, distance_matrix, rates, leg_duration_factor).total_cost
                    added = cost - base
                    loads = opt._load_at_positions(candidate, all_jobs)
                    peak = max(loads) if loads else 0.0
                    attempts.append(InsertionAttempt(
                        vehicle_id=vehicle.vehicle_id,
                        pickup_position=pickup_pos,
                        delivery_position=delivery_pos,
                        feasible=True,
                        failure_reason=None,
                        peak_load_after=peak,
                        incremental_cost=added,
                    ))
                else:
                    # Determine failure reason
                    failure = "CAPACITY"
                    # Check if it's a precedence violation
                    pos = {stop: i for i, stop in enumerate(candidate)}
                    precedence_ok = True
                    for j in all_jobs:
                        if j.pickup_idx in pos and j.delivery_idx in pos:
                            if pos[j.pickup_idx] >= pos[j.delivery_idx]:
                                precedence_ok = False
                                break
                    if not precedence_ok:
                        failure = "PRECEDENCE"
                    
                    # Calculate peak load even for infeasible
                    loads = opt._load_at_positions(candidate, all_jobs)
                    peak = max(loads) if loads else 0.0
                    
                    attempts.append(InsertionAttempt(
                        vehicle_id=vehicle.vehicle_id,
                        pickup_position=pickup_pos,
                        delivery_position=delivery_pos,
                        feasible=False,
                        failure_reason=failure,
                        peak_load_after=peak,
                        incremental_cost=None,
                    ))
            
            if not feasible:
                continue
            cost = evaluate_route(candidate, all_jobs, vehicle, duration_matrix, distance_matrix, rates, leg_duration_factor).total_cost
            added = cost - base
            if best is None or added < best[1]:
                best = (candidate, added)
    return attempts, best


def _build_vehicle_diagnostic(
    vehicle: FleetVehicle,
    route: list[int],
    placed: list[Job],
    job: Job,
    attempts: list[InsertionAttempt] | None,
) -> VehicleInsertionDiagnostic:
    """Build diagnostic summary for a vehicle."""
    current_loads = opt._load_at_positions(route, placed) if route else []
    current_peak = max(current_loads) if current_loads else 0.0
    static_remaining = (vehicle.capacity_kg - current_peak) if vehicle.capacity_kg is not None else None
    
    capacity_failures = sum(1 for a in (attempts or []) if a.failure_reason == "CAPACITY")
    precedence_failures = sum(1 for a in (attempts or []) if a.failure_reason == "PRECEDENCE")
    feasible = [a for a in (attempts or []) if a.feasible]
    
    best_peak = min((a.peak_load_after for a in feasible), default=None)
    best_cost = min((a.incremental_cost for a in feasible if a.incremental_cost is not None), default=None)
    best_pickup = next((a.pickup_position for a in feasible if a.peak_load_after == best_peak), None)
    best_delivery = next((a.delivery_position for a in feasible if a.peak_load_after == best_peak), None)
    
    return VehicleInsertionDiagnostic(
        vehicle_id=vehicle.vehicle_id,
        vehicle_capacity_kg=vehicle.capacity_kg,
        current_peak_load_kg=current_peak,
        static_remaining_capacity_kg=static_remaining,
        trip_weight_kg=job.load_weight_kg,
        total_pickup_positions_tested=len(set(a.pickup_position for a in (attempts or []))),
        total_delivery_positions_tested=len(set(a.delivery_position for a in (attempts or []))),
        capacity_failures=capacity_failures,
        precedence_failures=precedence_failures,
        feasible_insertions=len(feasible),
        best_peak_load_kg=best_peak,
        best_incremental_cost=best_cost,
        best_pickup_position=best_pickup,
        best_delivery_position=best_delivery,
    )

# A leg-level multiplier hook: (from_idx, to_idx) -> factor applied to that leg's
# base duration. Defaults to 1.0 everywhere. This is the seam where traffic,
# weather, and road-type models plug in later without touching the search loop.
LegDurationFactor = Callable[[int, int], float]

SECONDS_PER_HOUR = 3600.0
METERS_PER_KM = 1000.0
DEFAULT_MAX_ROUTE_DURATION_SECONDS = 12 * SECONDS_PER_HOUR
# Calibrated, utilization-based local proxies.  They are deliberately separate
# from the neutral external-factor hook above: absent traffic/weather/road data
# means no external adjustment, while recorded cargo and vehicle capacity are
# sufficient to model the vehicle's own load response.
LOAD_SPEED_DERATE_PER_UTILIZATION = 0.15
LOAD_FUEL_DERATE_PER_UTILIZATION = 0.25
MIN_SPEED_FRACTION = 0.30


@dataclass
class FleetVehicle:
    """One dispatchable vehicle. capacity_kg=None means unconstrained (matches
    opt.route_is_feasible's own convention). start_idx/end_idx are optional node
    indices into the SAME matrices the jobs index into - supply them to model a
    depot/hub the vehicle leaves from and returns to; leave them None for an open
    route, which is today's single-vehicle behavior."""

    vehicle_id: str
    capacity_kg: float | None = None
    avg_kmpl_rated: float | None = None
    fuel_price_per_l: float | None = None
    fixed_cost: float = 0.0
    driver_id: str | None = None
    start_idx: int | None = None
    end_idx: int | None = None
    # Per-vehicle rates. Rates are properties of a specific truck and a specific
    # driver, so a heterogeneous fleet cannot be costed from one shared pair -
    # these take precedence over the fleet-wide CostRates fallback.
    cost_per_km: float | None = None
    driver_cost_per_hour: float | None = None
    # Complete depot-to-depot limit; the default deliberately includes hub legs.
    max_route_duration_seconds: float = DEFAULT_MAX_ROUTE_DURATION_SECONDS


@dataclass
class CostRates:
    """Planning rates for the cost-denominated objective. Every field is
    optional: when a rate is absent its term is simply omitted rather than
    guessed. If NO monetary term can be computed at all (no fuel data, no rates),
    evaluate_route falls back to using duration-in-seconds as the cost proxy so
    the solver still has a meaningful gradient - the same objective the
    single-vehicle path uses by default."""

    driver_cost_per_hour: float | None = None
    operating_cost_per_km: float | None = None


@dataclass
class RouteMetrics:
    distance_meters: float = 0.0
    duration_seconds: float = 0.0
    fuel_liters: float = 0.0
    fuel_cost: float = 0.0
    driver_cost: float = 0.0
    operating_cost: float = 0.0
    fixed_cost: float = 0.0
    peak_load_kg: float = 0.0
    total_cost: float = 0.0
    # An empty route/fleet has no priced movement. It must not claim a monetary
    # total merely because the dataclass supplied a default value.
    cost_is_monetary: bool = False


@dataclass
class VehicleRoute:
    vehicle_id: str
    driver_id: str | None
    route: list[int]  # job stops only, in visiting order (depot excluded - see full_sequence)
    trip_ids: list[str]
    metrics: RouteMetrics

    def full_sequence(self, vehicle: FleetVehicle) -> list[int]:
        """Visiting order including depot legs, for display/geometry."""
        seq: list[int] = []
        if vehicle.start_idx is not None:
            seq.append(vehicle.start_idx)
        seq.extend(self.route)
        if vehicle.end_idx is not None:
            seq.append(vehicle.end_idx)
        return seq


@dataclass
class FleetSolution:
    routes: list[VehicleRoute] = field(default_factory=list)
    unassigned_trip_ids: list[str] = field(default_factory=list)
    totals: RouteMetrics = field(default_factory=RouteMetrics)
    feasible: bool = True
    # Diagnostic information for unassigned trips
    unassigned_diagnostics: list[TripAssignmentDiagnostic] = field(default_factory=list)

    @property
    def vehicles_used(self) -> int:
        return sum(1 for r in self.routes if r.route)


def _load_utilization(load_on_leg_kg: float, capacity_kg: float | None) -> float:
    """Recorded load expressed against this vehicle's capacity.

    Without a recorded capacity, fuel/time remain unadjusted rather than
    applying a made-up raw-kg multiplier.
    """
    if capacity_kg is None or capacity_kg <= 0:
        return 0.0
    return max(0.0, min(load_on_leg_kg / capacity_kg, 1.0))


def _load_speed_factor(load_on_leg_kg: float, capacity_kg: float | None) -> float:
    utilization = _load_utilization(load_on_leg_kg, capacity_kg)
    return max(1.0 - LOAD_SPEED_DERATE_PER_UTILIZATION * utilization, MIN_SPEED_FRACTION)


def _effective_kmpl(rated_kmpl: float, load_on_leg_kg: float, capacity_kg: float | None) -> float:
    """Load-derated mileage using utilization, never raw kilograms."""
    utilization = _load_utilization(load_on_leg_kg, capacity_kg)
    return rated_kmpl / (1.0 + LOAD_FUEL_DERATE_PER_UTILIZATION * utilization)


def _legs_with_load(
    route: list[int], jobs: list[Job], vehicle: FleetVehicle
) -> list[tuple[int, int, float]]:
    """(from_idx, to_idx, load_carried_on_this_leg) for every leg the vehicle
    drives, including the depot->first-stop and last-stop->depot legs when a
    depot is configured.

    load_carried is route STATE, not an edge property: the same (i, j) pair
    carries different loads in different candidate routes depending on which
    pickups happened earlier. This is why no load matrix is precomputed anywhere.
    """
    if not route:
        return []

    loads = opt._load_at_positions(route, jobs)
    legs: list[tuple[int, int, float]] = []

    if vehicle.start_idx is not None:
        legs.append((vehicle.start_idx, route[0], 0.0))  # leaves the depot empty

    for k in range(len(route) - 1):
        legs.append((route[k], route[k + 1], loads[k]))

    if vehicle.end_idx is not None:
        # Every job's delivery is in the route (precedence guarantees it), so the
        # vehicle is empty on the return leg.
        legs.append((route[-1], vehicle.end_idx, loads[-1] if loads else 0.0))

    return legs


def evaluate_route(
    route: list[int],
    jobs: list[Job],
    vehicle: FleetVehicle,
    duration_matrix: Matrix,
    distance_matrix: Matrix,
    rates: CostRates | None = None,
    leg_duration_factor: LegDurationFactor | None = None,
) -> RouteMetrics:
    """Full metrics for one vehicle's route. Cost is monetary when any rate/fuel
    data is available, otherwise duration-in-seconds as a proxy (flagged via
    cost_is_monetary so callers never mistake one for the other)."""
    metrics = RouteMetrics()
    if not route:
        metrics.cost_is_monetary = False
        return metrics

    rates = rates or CostRates()
    # Per-vehicle rate wins; the fleet-wide pair is only a fallback for callers
    # that haven't got per-vehicle figures.
    per_km = vehicle.cost_per_km if vehicle.cost_per_km is not None else rates.operating_cost_per_km
    per_hour = (
        vehicle.driver_cost_per_hour
        if vehicle.driver_cost_per_hour is not None
        else rates.driver_cost_per_hour
    )
    legs = _legs_with_load(route, jobs, vehicle)
    can_fuel = vehicle.avg_kmpl_rated is not None and vehicle.avg_kmpl_rated > 0 and vehicle.fuel_price_per_l is not None

    for i, j, load_on_leg in legs:
        distance_km = distance_matrix[i][j] / METERS_PER_KM
        external_factor = leg_duration_factor(i, j) if leg_duration_factor else 1.0
        # The route clock is sequential: the current leg's carried load affects
        # its travel time before the next stop changes that load.
        duration = duration_matrix[i][j] * external_factor / _load_speed_factor(load_on_leg, vehicle.capacity_kg)

        metrics.distance_meters += distance_matrix[i][j]
        metrics.duration_seconds += duration

        if can_fuel:
            liters = distance_km / _effective_kmpl(vehicle.avg_kmpl_rated, load_on_leg, vehicle.capacity_kg)
            metrics.fuel_liters += liters
            metrics.fuel_cost += liters * vehicle.fuel_price_per_l

    loads = opt._load_at_positions(route, jobs)
    metrics.peak_load_kg = max(loads) if loads else 0.0

    if per_hour is not None:
        metrics.driver_cost = (metrics.duration_seconds / SECONDS_PER_HOUR) * per_hour
    if per_km is not None:
        metrics.operating_cost = (metrics.distance_meters / METERS_PER_KM) * per_km
    metrics.fixed_cost = vehicle.fixed_cost

    monetary = metrics.fuel_cost + metrics.driver_cost + metrics.operating_cost + metrics.fixed_cost
    has_any_monetary = can_fuel or per_hour is not None or per_km is not None

    if has_any_monetary:
        metrics.total_cost = monetary
        metrics.cost_is_monetary = True
    else:
        # No cost data at all - fall back to the duration objective so the search
        # still has something meaningful to minimize.
        metrics.total_cost = metrics.duration_seconds + vehicle.fixed_cost
        metrics.cost_is_monetary = False

    return metrics


def _route_feasible(route: list[int], jobs: list[Job], vehicle: FleetVehicle) -> bool:
    """Hard constraints only, delegated wholesale to opt.route_is_feasible -
    precedence, no-duplicates, and capacity-at-every-stop. Depot nodes are
    excluded from `route` by construction, so they can never be mistaken for a
    job stop or trip a duplicate check when start_idx == end_idx."""
    if any(job.allowed_vehicle_ids and vehicle.vehicle_id not in job.allowed_vehicle_ids for job in jobs):
        return False
    return opt.route_is_feasible(route, jobs, vehicle.capacity_kg)


def _candidate_feasible(
    route: list[int], jobs: list[Job], vehicle: FleetVehicle,
    duration_matrix: Matrix, distance_matrix: Matrix, rates: CostRates | None,
    leg_duration_factor: LegDurationFactor | None,
) -> bool:
    """Hard route checks, including the configured complete hub round trip."""
    return _route_feasible(route, jobs, vehicle) and (
        evaluate_route(route, jobs, vehicle, duration_matrix, distance_matrix, rates, leg_duration_factor).duration_seconds
        <= vehicle.max_route_duration_seconds + 1e-6
    )


def _try_insert(
    route: list[int],
    placed: list[Job],
    job: Job,
    vehicle: FleetVehicle,
    duration_matrix: Matrix,
    distance_matrix: Matrix,
    rates: CostRates | None,
    leg_duration_factor: LegDurationFactor | None,
) -> tuple[list[int], float] | None:
    """Cheapest feasible (pickup_pos, delivery_pos) insertion of `job` into one
    vehicle's route, scored by the change in that vehicle's total cost. Returns
    (new_route, added_cost) or None if nothing feasible."""
    if not route:
        candidate = [job.pickup_idx, job.delivery_idx]
        if not _candidate_feasible(candidate, [job], vehicle, duration_matrix, distance_matrix, rates, leg_duration_factor):
            return None
        cost = evaluate_route(candidate, [job], vehicle, duration_matrix, distance_matrix, rates, leg_duration_factor).total_cost
        return candidate, cost

    all_jobs = placed + [job]
    base = evaluate_route(route, placed, vehicle, duration_matrix, distance_matrix, rates, leg_duration_factor).total_cost

    best: tuple[list[int], float] | None = None
    n = len(route)
    for pickup_pos in range(n + 1):
        for delivery_pos in range(pickup_pos, n + 1):
            candidate = opt.insert_pair(route, job, pickup_pos, delivery_pos)
            if not _candidate_feasible(candidate, all_jobs, vehicle, duration_matrix, distance_matrix, rates, leg_duration_factor):
                continue
            cost = evaluate_route(candidate, all_jobs, vehicle, duration_matrix, distance_matrix, rates, leg_duration_factor).total_cost
            added = cost - base
            if best is None or added < best[1]:
                best = (candidate, added)
    return best


def best_insertion_across_fleet(
    job: Job,
    assignments: list[list[int]],
    assigned_jobs: list[list[Job]],
    vehicles: list[FleetVehicle],
    duration_matrix: Matrix,
    distance_matrix: Matrix,
    rates: CostRates | None = None,
    leg_duration_factor: LegDurationFactor | None = None,
    debug: bool = False,
) -> tuple[int, list[int], float] | None:
    """Cheapest place for `job` anywhere in the fleet. Returns
    (vehicle_index, new_route_for_that_vehicle, added_cost), or None when no
    vehicle can feasibly take it.

    Because an empty vehicle's first job pays that vehicle's fixed_cost, a
    fleet with fixed costs naturally consolidates onto fewer vehicles unless
    spreading out genuinely saves more than the fixed cost - which is how
    "don't force every vehicle to be used" falls out of the objective rather
    than needing a special rule.
    """
    best: tuple[int, list[int], float] | None = None
    for v_idx, vehicle in enumerate(vehicles):
        attempts, result = _try_insert_with_diagnostics(
            assignments[v_idx], assigned_jobs[v_idx], job, vehicle,
            duration_matrix, distance_matrix, rates, leg_duration_factor, debug
        )
        if result is None:
            continue
        new_route, added = result
        if best is None or added < best[2]:
            best = (v_idx, new_route, added)
    return best


def _hub_pickup_priority(
    job: Job,
    vehicles: list[FleetVehicle],
    distance_matrix: Matrix,
) -> tuple[float, float, str]:
    """Order initial insertions by the closest compatible hub-to-pickup leg.

    This is only the construction layer: the subsequent insertion still tests
    every legal pickup/drop position and selects the lowest complete operating
    cost.  It gives geographically local work a sensible first placement
    without turning a nearest-hub heuristic into a hard assignment rule.
    """
    approaches = [
        distance_matrix[vehicle.start_idx][job.pickup_idx]
        for vehicle in vehicles
        if vehicle.start_idx is not None
        and (not job.allowed_vehicle_ids or vehicle.vehicle_id in job.allowed_vehicle_ids)
    ]
    return (min(approaches, default=float("inf")), -job.load_weight_kg, job.trip_id)


def construct_fleet(
    jobs: list[Job],
    vehicles: list[FleetVehicle],
    duration_matrix: Matrix,
    distance_matrix: Matrix,
    rates: CostRates | None = None,
    leg_duration_factor: LegDurationFactor | None = None,
) -> tuple[list[list[int]], list[list[Job]], list[Job]]:
    """Greedy cheapest-insertion across the fleet. Jobs that fit nowhere are
    returned as unassigned rather than silently dropped or force-fitted."""
    assignments: list[list[int]] = [[] for _ in vehicles]
    assigned_jobs: list[list[Job]] = [[] for _ in vehicles]
    unassigned: list[Job] = []

    # First seed the fleet by proximity from each compatible vehicle's hub to
    # the pickup.  Weight remains the tie-breaker because bulky jobs have fewer
    # feasible homes.  Drops are never pre-sorted: pair insertion chooses their
    # positions alongside pickups and retains precedence/capacity constraints.
    for job in sorted(jobs, key=lambda j: _hub_pickup_priority(j, vehicles, distance_matrix)):
        placement = best_insertion_across_fleet(
            job, assignments, assigned_jobs, vehicles,
            duration_matrix, distance_matrix, rates, leg_duration_factor,
        )
        if placement is None:
            unassigned.append(job)
            continue
        v_idx, new_route, _ = placement
        assignments[v_idx] = new_route
        assigned_jobs[v_idx].append(job)

    return assignments, assigned_jobs, unassigned


def compute_unassigned_diagnostics(
    unassigned_jobs: list[Job],
    vehicles: list[FleetVehicle],
    duration_matrix: Matrix,
    distance_matrix: Matrix,
    rates: CostRates | None = None,
    leg_duration_factor: LegDurationFactor | None = None,
) -> list[TripAssignmentDiagnostic]:
    """Compute detailed diagnostics for each unassigned job explaining WHY it couldn't be assigned."""
    diagnostics: list[TripAssignmentDiagnostic] = []
    
    for job in unassigned_jobs:
        vehicle_diagnostics: list[VehicleInsertionDiagnostic] = []
        all_capacity_failures = 0
        all_precedence_failures = 0
        all_positions_tested = 0
        best_peak_overall: float | None = None
        
        for vehicle in vehicles:
            attempts, _ = _try_insert_with_diagnostics(
                [], [], job, vehicle,
                duration_matrix, distance_matrix, rates, leg_duration_factor, debug=True
            )
            v_diag = _build_vehicle_diagnostic(vehicle, [], [], job, attempts)
            vehicle_diagnostics.append(v_diag)
            
            all_capacity_failures += v_diag.capacity_failures
            all_precedence_failures += v_diag.precedence_failures
            all_positions_tested += v_diag.total_pickup_positions_tested * v_diag.total_delivery_positions_tested
            if v_diag.best_peak_load_kg is not None:
                if best_peak_overall is None or v_diag.best_peak_load_kg < best_peak_overall:
                    best_peak_overall = v_diag.best_peak_load_kg
        
        # Determine primary failure reason
        primary_reason = "NO_FEASIBLE_INSERTION"
        if all_capacity_failures > 0 and all_precedence_failures == 0:
            primary_reason = "CAPACITY"
        elif all_precedence_failures > 0 and all_capacity_failures == 0:
            primary_reason = "PICKUP_DROP_CONSTRAINT"
        elif all_capacity_failures > 0 and all_precedence_failures > 0:
            primary_reason = "CAPACITY_AND_PRECEDENCE"
        
        # Check if trip exceeds all vehicle capacities
        max_capacity = max((v.capacity_kg for v in vehicles if v.capacity_kg is not None), default=None)
        exceeds_all = max_capacity is not None and job.load_weight_kg > max_capacity
        if exceeds_all:
            primary_reason = "VEHICLE_INCOMPATIBLE"
        
        diagnostics.append(TripAssignmentDiagnostic(
            trip_id=job.trip_id,
            trip_weight_kg=job.load_weight_kg,
            vehicle_diagnostics=vehicle_diagnostics,
            assigned_vehicle_id=None,
            assigned_pickup_position=None,
            assigned_delivery_position=None,
            assigned_peak_load_kg=None,
            assigned_incremental_cost=None,
            status="UNASSIGNED" if not exceeds_all else "EXCEEDS_ALL_VEHICLES",
            minimum_required_capacity_kg=best_peak_overall,
            primary_failure_reason=primary_reason,
            capacity_failures=all_capacity_failures,
            precedence_failures=all_precedence_failures,
            total_positions_tested=all_positions_tested,
        ))
    
    return diagnostics


def _fleet_cost(
    assignments: list[list[int]],
    assigned_jobs: list[list[Job]],
    vehicles: list[FleetVehicle],
    duration_matrix: Matrix,
    distance_matrix: Matrix,
    rates: CostRates | None,
    leg_duration_factor: LegDurationFactor | None,
) -> float:
    return sum(
        evaluate_route(
            assignments[i], assigned_jobs[i], vehicles[i],
            duration_matrix, distance_matrix, rates, leg_duration_factor,
        ).total_cost
        for i in range(len(vehicles))
    )


def fleet_solve(
    jobs: list[Job],
    vehicles: list[FleetVehicle],
    duration_matrix: Matrix,
    distance_matrix: Matrix,
    rates: CostRates | None = None,
    leg_duration_factor: LegDurationFactor | None = None,
    iterations: int = 150,
    destroy_fraction: float = 0.3,
    seed: int | None = None,
) -> FleetSolution:
    """Construct a fleet assignment with AUTOMATIC VEHICLE COUNT ESCALATION.
    
    The optimizer now automatically determines the optimal number of vehicles:
    1. First checks if any individual trip exceeds ALL vehicle capacities
    2. Tries with 1 vehicle, then 2, 3, ... up to all available vehicles
    3. Among all feasible solutions, picks the one with minimum total fleet cost
    4. Fixed costs naturally prevent unnecessary vehicle activation
    
    Hard constraints are always evaluated before cost: an infeasible candidate is
    discarded outright in _try_insert, never scored and never allowed to win on
    a lower objective. Capacity and precedence come from opt.route_is_feasible
    unchanged.
    """
    if not vehicles:
        raise ValueError("fleet_solve() requires at least one vehicle")
    if not jobs:
        raise ValueError("fleet_solve() requires at least one job")
    
    return _find_best_feasible_solution(
        jobs, vehicles, duration_matrix, distance_matrix,
        rates, leg_duration_factor, iterations, destroy_fraction, seed
    )


def _check_individual_trip_feasibility(jobs: list[Job], vehicles: list[FleetVehicle]) -> list[str]:
    """Check if any individual trip exceeds all vehicle capacities.
    Returns list of trip_ids that cannot be served by any vehicle."""
    unservable = []
    for job in jobs:
        eligible = [
            vehicle for vehicle in vehicles
            if not job.allowed_vehicle_ids or vehicle.vehicle_id in job.allowed_vehicle_ids
        ]
        # A job with no compatible vehicle is just as unservable as one that is
        # too heavy.  Looking at the fleet-wide maximum here used to let an
        # incompatible truck make a job appear feasible until much later in
        # the search.
        if not eligible or all(
            vehicle.capacity_kg is not None and job.load_weight_kg > vehicle.capacity_kg
            for vehicle in eligible
        ):
            unservable.append(job.trip_id)
    return unservable


def _vehicle_cost_priority(
    vehicle: FleetVehicle,
    jobs: list[Job],
    duration_matrix: Matrix,
    distance_matrix: Matrix,
    rates: CostRates | None,
    leg_duration_factor: LegDurationFactor | None,
) -> tuple[float, str]:
    """Rank a vehicle for bounded combination search by its cheapest feasible
    one-job route cost, not capacity.

    `evaluate_route` includes hub -> pickup and delivery -> end-hub legs, so a
    closer compatible depot naturally ranks ahead when it reduces the complete
    fleet-cost objective. This is only a search ordering heuristic; final
    selection below still compares complete feasible fleets by total_cost.
    """
    costs = [
        evaluate_route(
            [job.pickup_idx, job.delivery_idx], [job], vehicle,
            duration_matrix, distance_matrix, rates, leg_duration_factor,
        ).total_cost
        for job in jobs
        if _candidate_feasible(
            [job.pickup_idx, job.delivery_idx], [job], vehicle,
            duration_matrix, distance_matrix, rates, leg_duration_factor,
        )
    ]
    return (min(costs) if costs else float("inf"), vehicle.vehicle_id)


def _solve_with_vehicle_count(
    jobs: list[Job],
    vehicles: list[FleetVehicle],  # subset of vehicles to try
    all_vehicles: list[FleetVehicle],  # all available vehicles (for building full solution)
    duration_matrix: Matrix,
    distance_matrix: Matrix,
    rates: CostRates | None = None,
    leg_duration_factor: LegDurationFactor | None = None,
    iterations: int = 150,
    destroy_fraction: float = 0.3,
    seed: int | None = None,
) -> FleetSolution | None:
    """Try to solve with the given vehicles. Returns None if no feasible solution exists."""
    if not vehicles:
        return None
    
    # Map from subset vehicle index to full vehicle list index
    vehicle_indices = [all_vehicles.index(v) for v in vehicles]
    
    rng = random.Random(seed)
    assignments, assigned_jobs, unassigned = construct_fleet(
        jobs, vehicles, duration_matrix, distance_matrix, rates, leg_duration_factor,
    )
    
    if unassigned:
        return None  # Some jobs couldn't be assigned
    
    best_cost = _fleet_cost(assignments, assigned_jobs, vehicles, duration_matrix, distance_matrix, rates, leg_duration_factor)
    
    placeable = [j for j in jobs if j not in unassigned]
    if placeable:
        for _ in range(iterations):
            num_remove = max(1, round(len(placeable) * destroy_fraction))
            removed = rng.sample(placeable, min(num_remove, len(placeable)))
            removed_stops = {j.pickup_idx for j in removed} | {j.delivery_idx for j in removed}
            
            trial_assignments = [[s for s in r if s not in removed_stops] for r in assignments]
            trial_jobs = [[j for j in js if j not in removed] for js in assigned_jobs]
            
            order = list(removed)
            rng.shuffle(order)
            failed = False
            for job in order:
                placement = best_insertion_across_fleet(
                    job, trial_assignments, trial_jobs, vehicles,
                    duration_matrix, distance_matrix, rates, leg_duration_factor,
                )
                if placement is None:
                    failed = True
                    break
                v_idx, new_route, _ = placement
                trial_assignments[v_idx] = new_route
                trial_jobs[v_idx].append(job)
            
            if failed:
                continue
            
            trial_cost = _fleet_cost(trial_assignments, trial_jobs, vehicles, duration_matrix, distance_matrix, rates, leg_duration_factor)
            if trial_cost < best_cost:
                assignments, assigned_jobs, best_cost = trial_assignments, trial_jobs, trial_cost
    
    # Build the result, re-verifying every route's hard constraints
    # Include ALL vehicles, even idle ones
    routes: list[VehicleRoute] = []
    totals = RouteMetrics()
    all_feasible = True
    
    # Map from subset index to assignments/assigned_jobs
    subset_to_assigned = {vehicle_indices[i]: (assignments[i], assigned_jobs[i]) for i in range(len(vehicles))}
    
    for v_idx, vehicle in enumerate(all_vehicles):
        if v_idx in subset_to_assigned:
            route, vjobs = subset_to_assigned[v_idx]
        else:
            route, vjobs = [], []
        metrics = evaluate_route(route, vjobs, vehicle, duration_matrix, distance_matrix, rates, leg_duration_factor)
        if route and not _candidate_feasible(
            route, vjobs, vehicle, duration_matrix, distance_matrix, rates, leg_duration_factor,
        ):
            all_feasible = False
        routes.append(
            VehicleRoute(
                vehicle_id=vehicle.vehicle_id,
                driver_id=vehicle.driver_id,
                route=route,
                trip_ids=[j.trip_id for j in vjobs],
                metrics=metrics,
            )
        )
        totals.distance_meters += metrics.distance_meters
        totals.duration_seconds += metrics.duration_seconds
        totals.fuel_liters += metrics.fuel_liters
        totals.fuel_cost += metrics.fuel_cost
        totals.driver_cost += metrics.driver_cost
        totals.operating_cost += metrics.operating_cost
        totals.fixed_cost += metrics.fixed_cost
        totals.total_cost += metrics.total_cost
        totals.peak_load_kg = max(totals.peak_load_kg, metrics.peak_load_kg)
        # An aggregate is monetary only when every dispatched route was fully
        # costed.  Idle vehicles have a zero/proxy metric and must not overwrite
        # the truth of the active fleet total.
        if route:
            totals.cost_is_monetary = (
                metrics.cost_is_monetary
                if not any(existing.route for existing in routes[:-1])
                else totals.cost_is_monetary and metrics.cost_is_monetary
            )
    
    if not all_feasible:
        return None
    
    return FleetSolution(
        routes=routes,
        unassigned_trip_ids=[],
        totals=totals,
        feasible=True,
    )


def _find_best_feasible_solution(
    jobs: list[Job],
    vehicles: list[FleetVehicle],
    duration_matrix: Matrix,
    distance_matrix: Matrix,
    rates: CostRates | None = None,
    leg_duration_factor: LegDurationFactor | None = None,
    iterations: int = 150,
    destroy_fraction: float = 0.3,
    seed: int | None = None,
) -> FleetSolution:
    """Try with increasing vehicle counts and return the best feasible solution.
    
    Strategy:
    1. Check if any individual trip exceeds ALL vehicle capacities - these are marked as unassignable
    2. Try with 1 vehicle, then 2, 3, ... up to all available vehicles
    3. For each vehicle count, try all combinations of that many vehicles
    4. Among all feasible solutions, pick the one with minimum total cost
    """
    # Check for individual trips that exceed all vehicle capacities
    unservable = _check_individual_trip_feasibility(jobs, vehicles)
    
    # Separate servable and unservable jobs
    servable_jobs = [j for j in jobs if j.trip_id not in unservable]
    
    # If no servable jobs, return empty solution with all jobs unassigned
    if not servable_jobs:
        return FleetSolution(
            routes=[],
            unassigned_trip_ids=[j.trip_id for j in jobs],
            totals=RouteMetrics(),
            feasible=False,
        )
    
    # Search lower-cost depot-to-depot candidates first. Capacity remains a hard
    # feasibility constraint; it is deliberately not the fleet objective.
    vehicles_sorted = sorted(
        vehicles,
        key=lambda vehicle: _vehicle_cost_priority(
            vehicle, servable_jobs, duration_matrix, distance_matrix, rates, leg_duration_factor,
        ),
    )
    
    best_solution: FleetSolution | None = None
    best_cost = float('inf')
    
    # Try with 1 vehicle, then 2, 3, ... up to all vehicles
    for num_vehicles in range(1, len(vehicles_sorted) + 1):
        # Try combinations of vehicles - for performance, try a few combinations
        # Priority: combinations with larger capacity vehicles first
        
        # For small fleet sizes, try all combinations; for larger, sample
        vehicle_combos = list(combinations(vehicles_sorted, num_vehicles))
        
        # Every offered subset participates in the comparison.  Truncating this
        # list made the answer depend on input ordering and could skip the
        # cheapest compatible fleet, which conflicts with the cost objective.
        for combo in vehicle_combos:
            solution = _solve_with_vehicle_count(
                servable_jobs, list(combo), vehicles_sorted, duration_matrix, distance_matrix,
                rates, leg_duration_factor, iterations, destroy_fraction, seed
            )
            if solution and solution.feasible:
                if solution.totals.total_cost < best_cost:
                    best_solution = solution
                    best_cost = solution.totals.total_cost
    
    if best_solution is None:
        # No feasible solution found with any vehicle count - compute diagnostics for all servable jobs
        # that couldn't be assigned even with all vehicles
        assignments, assigned_jobs, unassigned = construct_fleet(
            servable_jobs, vehicles_sorted, duration_matrix, distance_matrix, rates, leg_duration_factor,
        )
        diagnostics = compute_unassigned_diagnostics(unassigned, vehicles_sorted, duration_matrix, distance_matrix, rates, leg_duration_factor)
        # Add unservable as diagnostics too
        for trip_id in unservable:
            job = next(j for j in jobs if j.trip_id == trip_id)
            diagnostics.append(TripAssignmentDiagnostic(
                trip_id=trip_id,
                trip_weight_kg=job.load_weight_kg,
                vehicle_diagnostics=[],
                assigned_vehicle_id=None,
                assigned_pickup_position=None,
                assigned_delivery_position=None,
                assigned_peak_load_kg=None,
                assigned_incremental_cost=None,
                status="EXCEEDS_ALL_VEHICLES",
                minimum_required_capacity_kg=None,
                primary_failure_reason="VEHICLE_INCOMPATIBLE",
                capacity_failures=0,
                precedence_failures=0,
                total_positions_tested=0,
            ))
        return FleetSolution(
            routes=[],
            unassigned_trip_ids=[j.trip_id for j in jobs],
            totals=RouteMetrics(),
            feasible=False,
            unassigned_diagnostics=diagnostics,
        )
    
    # Add unservable trips to unassigned list
    if unservable:
        best_solution.unassigned_trip_ids.extend(unservable)
    
    # Compute diagnostics for any unassigned trips in the best solution
    if best_solution.unassigned_trip_ids:
        unassigned_jobs = [j for j in jobs if j.trip_id in best_solution.unassigned_trip_ids]
        diagnostics = compute_unassigned_diagnostics(unassigned_jobs, vehicles_sorted, duration_matrix, distance_matrix, rates, leg_duration_factor)
        best_solution.unassigned_diagnostics = diagnostics
    
    return best_solution


def explain_solution(solution: FleetSolution, vehicles: list[FleetVehicle]) -> list[str]:
    """Human-readable rationale per vehicle, for dispatcher trust and debugging.
    Reports only quantities actually computed - never invented justification."""
    by_id = {v.vehicle_id: v for v in vehicles}
    lines: list[str] = []
    for route in solution.routes:
        if not route.route:
            lines.append(f"{route.vehicle_id}: not used - no assignment lowered total fleet cost.")
            continue
        v = by_id[route.vehicle_id]
        m = route.metrics
        cap = f"{m.peak_load_kg:,.0f} / {v.capacity_kg:,.0f} kg" if v.capacity_kg else f"{m.peak_load_kg:,.0f} kg (uncapped)"
        parts = [
            f"{route.vehicle_id}: {len(route.trip_ids)} trip(s) [{', '.join(route.trip_ids)}]",
            f"peak load {cap}",
            f"{m.distance_meters / METERS_PER_KM:,.1f} km",
            f"{m.duration_seconds / 60:,.0f} min",
        ]
        if m.fuel_liters:
            parts.append(f"{m.fuel_liters:,.1f} L fuel")
        parts.append(
            f"cost {m.total_cost:,.0f}" + ("" if m.cost_is_monetary else " (duration proxy - no cost rates supplied)")
        )
        lines.append(" | ".join(parts))
    if solution.unassigned_trip_ids:
        lines.append(
            f"Unassigned: {', '.join(solution.unassigned_trip_ids)} - no vehicle could carry these within capacity."
        )
    return lines
