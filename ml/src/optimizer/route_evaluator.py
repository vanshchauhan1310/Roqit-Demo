"""Route Evaluator - Core evaluation engine for multi-vehicle optimizer.

Evaluates routes sequentially, leg by leg, tracking dynamic load, time, and
applying speed/fuel/cost models. This replaces the matrix-based evaluation
with a physics-based, time-aware approach.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Callable, Optional

from src.optimizer.opt import Job, Matrix


class RoadClass(Enum):
    """Road classification for speed/fuel adjustments."""
    HIGHWAY = "highway"
    STATE_ROAD = "state_road"
    CITY_ROAD = "city_road"
    RURAL_ROAD = "rural_road"
    UNKNOWN = "unknown"


class WeatherCondition(Enum):
    """Weather conditions affecting speed/fuel."""
    CLEAR = "clear"
    RAIN = "rain"
    FOG = "fog"
    EXTREME_HEAT = "extreme_heat"
    STORM = "storm"
    UNKNOWN = "unknown"


class TrafficDensity(Enum):
    """Traffic density levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    SEVERE = "severe"
    UNKNOWN = "unknown"


@dataclass
class VehicleSpec:
    """Vehicle specifications for evaluation."""
    vehicle_id: str
    capacity_kg: float
    avg_kmpl_rated: float
    fuel_price_per_l: float
    fixed_cost: float = 0.0
    cost_per_km: float = 0.0
    driver_cost_per_hour: float = 0.0
    base_speed_kmph: float = 60.0  # Base speed on highway in clear conditions


@dataclass
class LegContext:
    """Context for a single leg evaluation."""
    from_idx: int
    to_idx: int
    distance_m: float
    base_duration_s: float
    load_kg: float
    departure_time: datetime
    road_class: RoadClass = RoadClass.UNKNOWN
    weather: WeatherCondition = WeatherCondition.UNKNOWN
    traffic: TrafficDensity = TrafficDensity.UNKNOWN


@dataclass
class LegResult:
    """Result of evaluating a single leg."""
    distance_km: float
    travel_time_s: float
    speed_kmph: float
    fuel_liters: float
    fuel_cost: float
    arrival_time: datetime
    load_ratio: float
    load_factor: float
    road_factor: float
    weather_factor: float
    traffic_factor: float
    composite_factor: float


@dataclass
class StopEvent:
    """Event at a stop (pickup or delivery)."""
    stop_idx: int
    job_id: str
    event_type: str  # "pickup" or "delivery"
    weight_kg: float
    load_before: float
    load_after: float
    arrival_time: datetime
    service_time_s: float
    departure_time: datetime


@dataclass
class RouteEvaluation:
    """Complete route evaluation result."""
    vehicle_id: str
    legs: list[LegResult] = field(default_factory=list)
    stop_events: list[StopEvent] = field(default_factory=list)
    total_distance_km: float = 0.0
    total_travel_time_s: float = 0.0
    total_service_time_s: float = 0.0
    total_waiting_time_s: float = 0.0
    total_fuel_liters: float = 0.0
    total_fuel_cost: float = 0.0
    peak_load_kg: float = 0.0
    driver_cost: float = 0.0
    distance_cost: float = 0.0
    fixed_cost: float = 0.0
    toll_cost: float = 0.0
    total_cost: float = 0.0
    feasible: bool = True
    violation_reason: str = ""

    # Public cost vocabulary used by the fleet API/design.  Keep the explicit
    # accumulated field names above for backwards-compatible diagnostics.
    @property
    def distance_km(self) -> float:
        return self.total_distance_km

    @property
    def travel_time(self) -> float:
        return self.total_travel_time_s

    @property
    def fuel_liters(self) -> float:
        return self.total_fuel_liters

    @property
    def fuel_cost(self) -> float:
        return self.total_fuel_cost

    @property
    def fixed_vehicle_cost(self) -> float:
        return self.fixed_cost

    @property
    def peak_load(self) -> float:
        return self.peak_load_kg


# Default calibration constants - modular for future extension
LOAD_SPEED_DERATE_PER_UNIT_RATIO = 0.15  # 15% speed reduction at full load
MIN_SPEED_FRACTION_OF_BASE = 0.3  # Floor so speed never craters

LOAD_FUEL_DERATE_PER_UNIT_RATIO = 0.25  # 25% fuel increase at full load
MAX_FUEL_MULTIPLIER = 2.0  # Cap fuel multiplier

ROAD_SPEED_FACTORS = {
    RoadClass.HIGHWAY: 1.0,
    RoadClass.STATE_ROAD: 0.85,
    RoadClass.CITY_ROAD: 0.6,
    RoadClass.RURAL_ROAD: 0.75,
    RoadClass.UNKNOWN: 1.0,
}

ROAD_FUEL_FACTORS = {
    RoadClass.HIGHWAY: 1.0,
    RoadClass.STATE_ROAD: 1.05,
    RoadClass.CITY_ROAD: 1.25,
    RoadClass.RURAL_ROAD: 1.1,
    RoadClass.UNKNOWN: 1.0,
}

# There is no per-leg traffic or weather source in this application.  Keeping
# these calibrations neutral is deliberate: 1.0 means "no adjustment applied",
# not "there is no traffic/weather".  Replace these through the factor provider
# seams below when a calibrated source is available; do not invent values here.
WEATHER_SPEED_FACTORS = {condition: 1.0 for condition in WeatherCondition}
WEATHER_FUEL_FACTORS = {condition: 1.0 for condition in WeatherCondition}
TRAFFIC_SPEED_FACTORS = {density: 1.0 for density in TrafficDensity}
TRAFFIC_FUEL_FACTORS = {density: 1.0 for density in TrafficDensity}


def load_ratio(load_kg: float, capacity_kg: float) -> float:
    """Load ratio (0.0 to 1.0+). Returns 0 if capacity unknown."""
    if capacity_kg <= 0:
        return 0.0
    return min(load_kg / capacity_kg, 2.0)  # Cap at 2x for safety


def load_speed_factor(load_ratio: float) -> float:
    """Speed reduction factor from load. Neutral (1.0) at zero load."""
    if load_ratio <= 0:
        return 1.0
    factor = 1.0 - LOAD_SPEED_DERATE_PER_UNIT_RATIO * load_ratio
    return max(factor, MIN_SPEED_FRACTION_OF_BASE)


def load_fuel_factor(load_ratio: float) -> float:
    """Fuel increase factor from load. Neutral (1.0) at zero load."""
    if load_ratio <= 0:
        return 1.0
    factor = 1.0 + LOAD_FUEL_DERATE_PER_UNIT_RATIO * load_ratio
    return min(factor, MAX_FUEL_MULTIPLIER)


def compute_leg_speed(
    base_speed_kmph: float,
    load_ratio: float,
    road_class: RoadClass,
    weather: WeatherCondition,
    traffic: TrafficDensity,
) -> tuple[float, float, float, float, float]:
    """Compute effective speed and component factors.
    
    Returns: (effective_speed, load_factor, road_factor, weather_factor, traffic_factor)
    """
    load_f = load_speed_factor(load_ratio)
    road_f = ROAD_SPEED_FACTORS.get(road_class, 1.0)
    weather_f = WEATHER_SPEED_FACTORS.get(weather, 1.0)
    traffic_f = TRAFFIC_SPEED_FACTORS.get(traffic, 1.0)
    
    composite = load_f * road_f * weather_f * traffic_f
    effective = base_speed_kmph * composite
    
    return effective, load_f, road_f, weather_f, traffic_f


def compute_leg_fuel(
    distance_km: float,
    base_kmpl: float,
    load_ratio: float,
    road_class: RoadClass,
    weather: WeatherCondition,
    traffic: TrafficDensity,
    speed_kmph: float,
) -> tuple[float, float, float, float, float]:
    """Compute fuel consumption and component factors.
    
    Returns: (fuel_liters, load_factor, road_factor, weather_factor, traffic_factor)
    """
    load_f = load_fuel_factor(load_ratio)
    road_f = ROAD_FUEL_FACTORS.get(road_class, 1.0)
    weather_f = WEATHER_FUEL_FACTORS.get(weather, 1.0)
    traffic_f = TRAFFIC_FUEL_FACTORS.get(traffic, 1.0)
    
    composite = load_f * road_f * weather_f * traffic_f
    effective_kmpl = base_kmpl / composite
    fuel_liters = distance_km / effective_kmpl if effective_kmpl > 0 else 0.0
    
    return fuel_liters, load_f, road_f, weather_f, traffic_f


def evaluate_leg(
    ctx: LegContext,
    vehicle: VehicleSpec,
    get_road_class: Callable[[int, int], RoadClass] = lambda i, j: RoadClass.UNKNOWN,
    get_weather: Callable[[int, int, datetime], WeatherCondition] = lambda i, j, t: WeatherCondition.UNKNOWN,
    get_traffic: Callable[[int, int, datetime], TrafficDensity] = lambda i, j, t: TrafficDensity.UNKNOWN,
    get_speed_factor: Callable[[int, int, datetime, float], float] | None = None,
    get_fuel_factor: Callable[[int, int, datetime, float], float] | None = None,
) -> LegResult:
    """Evaluate a single leg with dynamic factors."""
    distance_km = ctx.distance_m / 1000.0
    load_r = load_ratio(ctx.load_kg, vehicle.capacity_kg)
    
    # Get dynamic factors for this leg at departure time
    road = get_road_class(ctx.from_idx, ctx.to_idx)
    weather = get_weather(ctx.from_idx, ctx.to_idx, ctx.departure_time)
    traffic = get_traffic(ctx.from_idx, ctx.to_idx, ctx.departure_time)
    
    # Compute effective speed
    speed, load_f, road_f, weather_f, traffic_f = compute_leg_speed(
        vehicle.base_speed_kmph, load_r, road, weather, traffic
    )
    # The neutral enum maps above intentionally make no claim about live
    # conditions. A real, calibrated provider may supply a time-aware composite
    # factor here; it is queried per leg at the route clock's departure time.
    if get_speed_factor is not None:
        traffic_f *= get_speed_factor(ctx.from_idx, ctx.to_idx, ctx.departure_time, load_r)
        speed = vehicle.base_speed_kmph * load_f * road_f * weather_f * traffic_f
    
    # Travel time = distance / speed
    travel_time_h = distance_km / speed if speed > 0 else 0.0
    travel_time_s = travel_time_h * 3600.0
    
    # Compute fuel
    fuel_l, _, _, _, _ = compute_leg_fuel(
        distance_km, vehicle.avg_kmpl_rated, load_r, road, weather, traffic, speed
    )
    if get_fuel_factor is not None:
        fuel_l *= get_fuel_factor(ctx.from_idx, ctx.to_idx, ctx.departure_time, load_r)
    
    arrival = ctx.departure_time + timedelta(seconds=travel_time_s)
    fuel_cost = fuel_l * vehicle.fuel_price_per_l
    
    composite = load_f * road_f * weather_f * traffic_f
    
    return LegResult(
        distance_km=distance_km,
        travel_time_s=travel_time_s,
        speed_kmph=speed,
        fuel_liters=fuel_l,
        fuel_cost=fuel_cost,
        arrival_time=arrival,
        load_ratio=load_r,
        load_factor=load_f,
        road_factor=road_f,
        weather_factor=weather_f,
        traffic_factor=traffic_f,
        composite_factor=composite,
    )


def evaluate_stop(
    stop_idx: int,
    job: Job,
    event_type: str,
    current_load: float,
    arrival_time: datetime,
    service_time_s: float = 300.0,  # 5 min default service time
) -> tuple[StopEvent, float]:
    """Process a pickup or delivery stop. Returns (event, new_load)."""
    if event_type == "pickup":
        new_load = current_load + job.load_weight_kg
    else:
        new_load = current_load - job.load_weight_kg
    
    departure = arrival_time + timedelta(seconds=service_time_s)
    
    event = StopEvent(
        stop_idx=stop_idx,
        job_id=job.trip_id,
        event_type=event_type,
        weight_kg=job.load_weight_kg,
        load_before=current_load,
        load_after=new_load,
        arrival_time=arrival_time,
        service_time_s=service_time_s,
        departure_time=departure,
    )
    
    return event, new_load


def evaluate_route(
    route: list[int],
    jobs: list[Job],
    vehicle: VehicleSpec,
    duration_matrix: Matrix,
    distance_matrix: Matrix,
    start_time: datetime,
    start_idx: Optional[int] = None,
    end_idx: Optional[int] = None,
    get_road_class: Callable[[int, int], RoadClass] = lambda i, j: RoadClass.UNKNOWN,
    get_weather: Callable[[int, int, datetime], WeatherCondition] = lambda i, j, t: WeatherCondition.UNKNOWN,
    get_traffic: Callable[[int, int, datetime], TrafficDensity] = lambda i, j, t: TrafficDensity.UNKNOWN,
    service_time_per_stop_s: float = 300.0,
    waiting_time_s: float = 0.0,
    get_driver_cost_per_hour: Callable[[datetime], float] | None = None,
    get_speed_factor: Callable[[int, int, datetime, float], float] | None = None,
    get_fuel_factor: Callable[[int, int, datetime, float], float] | None = None,
) -> RouteEvaluation:
    """Evaluate a complete route sequentially, leg by leg.
    
    This is the core evaluator that:
    1. Walks the route stop by stop
    2. Tracks load dynamically (pickup adds, delivery subtracts)
    3. Computes speed/fuel per leg using load_ratio and dynamic factors
    4. Updates clock after each leg for time-dependent factors
    5. Validates capacity at every stop
    6. Accumulates all costs
    """
    result = RouteEvaluation(vehicle_id=vehicle.vehicle_id)

    if not route:
        return result

    # A fixed vehicle cost applies only to a vehicle that is actually dispatched.
    result.fixed_cost = vehicle.fixed_cost
    
    # Build job lookup
    job_by_pickup = {j.pickup_idx: j for j in jobs}
    job_by_delivery = {j.delivery_idx: j for j in jobs}
    
    # Build full sequence including depot
    full_route = []
    if start_idx is not None:
        full_route.append(start_idx)
    full_route.extend(route)
    if end_idx is not None:
        full_route.append(end_idx)
    
    current_load = 0.0
    current_time = start_time
    peak_load = 0.0
    
    def process_stop(stop_idx: int) -> bool:
        """Apply the stop's load change and service time at ``current_time``.

        The caller owns the route clock.  Returning False leaves a complete,
        infeasible evaluation for diagnostic consumers instead of raising in the
        middle of the optimization search.
        """
        nonlocal current_load, current_time, peak_load
        if stop_idx in job_by_pickup:
            job = job_by_pickup[stop_idx]
            event_type = "pickup"
        elif stop_idx in job_by_delivery:
            job = job_by_delivery[stop_idx]
            event_type = "delivery"
        else:
            result.feasible = False
            result.violation_reason = f"Unknown route stop {stop_idx}"
            return False

        event, current_load = evaluate_stop(
            stop_idx, job, event_type, current_load, current_time, service_time_per_stop_s
        )
        result.stop_events.append(event)
        peak_load = max(peak_load, event.load_before, current_load)
        result.total_service_time_s += service_time_per_stop_s
        current_time = event.departure_time

        if current_load < -1e-9:
            result.feasible = False
            result.violation_reason = f"Delivery before pickup for {job.trip_id}"
            return False
        if current_load > vehicle.capacity_kg + 1e-9:
            result.feasible = False
            result.violation_reason = (
                f"Capacity exceeded at pickup {job.trip_id}: "
                f"{current_load:.0f} > {vehicle.capacity_kg:.0f} kg"
            )
            return False
        return True

    # An open route has no incoming depot leg, so its first stop must be applied
    # before evaluating its first outgoing leg.
    if start_idx is None and not process_stop(route[0]):
        result.peak_load_kg = peak_load
        return result
    
    for seq_idx in range(len(full_route) - 1):
        from_idx = full_route[seq_idx]
        to_idx = full_route[seq_idx + 1]
        
        # Get base distance and duration from matrices
        distance_m = distance_matrix[from_idx][to_idx]
        base_duration_s = duration_matrix[from_idx][to_idx]
        
        # Create leg context
        ctx = LegContext(
            from_idx=from_idx,
            to_idx=to_idx,
            distance_m=distance_m,
            base_duration_s=base_duration_s,
            load_kg=current_load,
            departure_time=current_time,
        )
        
        # Evaluate leg
        leg_result = evaluate_leg(
            ctx, vehicle, get_road_class, get_weather, get_traffic,
            get_speed_factor, get_fuel_factor,
        )
        result.legs.append(leg_result)
        
        # Update accumulators
        result.total_distance_km += leg_result.distance_km
        result.total_travel_time_s += leg_result.travel_time_s
        result.total_fuel_liters += leg_result.fuel_liters
        result.total_fuel_cost += leg_result.fuel_cost
        
        # Update clock
        current_time = leg_result.arrival_time
        
        # Process stop event (unless it's the final depot return)
        if seq_idx + 1 < len(full_route) - 1 or end_idx is None:
            stop_idx = full_route[seq_idx + 1]
            if not process_stop(stop_idx):
                result.peak_load_kg = peak_load
                return result
    
    # Final peak load check (after last delivery, before depot return)
    result.peak_load_kg = peak_load
    
    # Add waiting time if specified
    result.total_waiting_time_s = waiting_time_s
    current_time += timedelta(seconds=waiting_time_s)
    
    # Compute costs
    total_hours = (result.total_travel_time_s + result.total_service_time_s + result.total_waiting_time_s) / 3600.0
    
    if get_driver_cost_per_hour is not None:
        # Rate can change over the route (for example, an overtime boundary).
        # Charge each travel/service interval at the timestamp it starts.
        billed_seconds = 0.0
        for leg in result.legs:
            departure = leg.arrival_time - timedelta(seconds=leg.travel_time_s)
            result.driver_cost += leg.travel_time_s / 3600.0 * get_driver_cost_per_hour(departure)
            billed_seconds += leg.travel_time_s
        for event in result.stop_events:
            result.driver_cost += event.service_time_s / 3600.0 * get_driver_cost_per_hour(event.arrival_time)
            billed_seconds += event.service_time_s
        if result.total_waiting_time_s:
            result.driver_cost += result.total_waiting_time_s / 3600.0 * get_driver_cost_per_hour(current_time - timedelta(seconds=result.total_waiting_time_s))
            billed_seconds += result.total_waiting_time_s
    elif vehicle.driver_cost_per_hour > 0:
        result.driver_cost = total_hours * vehicle.driver_cost_per_hour
    
    if vehicle.cost_per_km > 0:
        result.distance_cost = result.total_distance_km * vehicle.cost_per_km
    
    result.total_cost = (
        result.fixed_cost
        + result.total_fuel_cost
        + result.driver_cost
        + result.distance_cost
        + result.toll_cost
    )
    
    return result


def evaluate_fleet(
    routes: dict[str, list[int]],  # vehicle_id -> route (job stops only)
    vehicle_jobs: dict[str, list[Job]],
    vehicles: dict[str, VehicleSpec],
    duration_matrix: Matrix,
    distance_matrix: Matrix,
    start_time: datetime,
    hub_indices: dict[str, tuple[Optional[int], Optional[int]]],  # vehicle_id -> (start_idx, end_idx)
    get_road_class: Callable[[int, int], RoadClass] = lambda i, j: RoadClass.UNKNOWN,
    get_weather: Callable[[int, int, datetime], WeatherCondition] = lambda i, j, t: WeatherCondition.UNKNOWN,
    get_traffic: Callable[[int, int, datetime], TrafficDensity] = lambda i, j, t: TrafficDensity.UNKNOWN,
    service_time_per_stop_s: float = 300.0,
) -> dict[str, RouteEvaluation]:
    """Evaluate all routes in a fleet."""
    results = {}
    for vehicle_id, route in routes.items():
        vehicle = vehicles[vehicle_id]
        jobs = vehicle_jobs.get(vehicle_id, [])
        start_idx, end_idx = hub_indices.get(vehicle_id, (None, None))
        
        results[vehicle_id] = evaluate_route(
            route=route,
            jobs=jobs,
            vehicle=vehicle,
            duration_matrix=duration_matrix,
            distance_matrix=distance_matrix,
            start_time=start_time,
            start_idx=start_idx,
            end_idx=end_idx,
            get_road_class=get_road_class,
            get_weather=get_weather,
            get_traffic=get_traffic,
            service_time_per_stop_s=service_time_per_stop_s,
        )
    return results


def fleet_total_cost(evaluations: dict[str, RouteEvaluation]) -> float:
    """Sum total cost across used vehicles only."""
    return sum(
        eval.total_cost
        for eval in evaluations.values()
        if eval.legs  # Only count vehicles that actually ran routes
    )
