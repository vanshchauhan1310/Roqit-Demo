from typing import Any, Literal

from pydantic import BaseModel


class OptimizeStopInput(BaseModel):
    key: str  # client-side stop identifier, echoed back in the optimized order
    latitude: float
    longitude: float
    trip_id: str
    stop_type: Literal["pickup", "delivery"]
    load_weight_kg: float | None = None  # meaningful on the pickup entry; ignored on delivery


class OptimizeVehicleInput(BaseModel):
    vehicle_id: str
    capacity_kg: float
    start_location: int  # index into stops array for depot location
    avg_kmpl_rated: float = 8.5
    fuel_price_per_l: float = 92.5


class DepotInput(BaseModel):
    """Explicit depot location (separate from pickup/delivery stops)."""
    key: str = "depot"
    latitude: float
    longitude: float
    address: str | None = None


class CostWeightsInput(BaseModel):
    alpha: float = 0.4   # duration weight
    delta: float = 0.2   # distance weight
    beta: float = 0.3    # fuel weight
    gamma: float = 0.1   # load (ton-km) weight
    lateness_weight: float = 60.0


class OptimizeRouteRequest(BaseModel):
    stops: list[OptimizeStopInput]
    vehicles: list[OptimizeVehicleInput] | None = None  # multi-vehicle support
    vehicle_capacity_kg: float | None = None  # legacy single vehicle support
    auto_generate_windows: bool = True
    start_time: int = 0
    vehicle_speed_kph: float = 40.0
    cost_weights: CostWeightsInput | None = None
    solver_time_limit_seconds: int = 10
    depot: DepotInput | None = None  # explicit depot; if omitted, uses first stop as fallback


class VehicleRouteOutput(BaseModel):
    vehicle_id: str
    stops: list[str]  # stop keys in optimized visiting order


class OptimizeRouteResponse(BaseModel):
    routes: list[VehicleRouteOutput] | None = None  # multi-vehicle response
    order: list[str] | None = None  # legacy single vehicle response
    total_duration_seconds: float
    total_distance_meters: float
    total_lateness_seconds: float = 0.0
    total_fuel_cost_rupees: float = 0.0
    total_load_ton_km: float = 0.0
    solver_used: Literal["or_tools", "fallback", "exact", "hybrid"]
    feasible: bool


# ---------------------------------------------------------------------------
# Multi-vehicle fleet optimization
# ---------------------------------------------------------------------------

# Typed outcomes so a predictable business rejection never surfaces as a 500.
# Values the optimize path cannot currently reach (no traffic/weather provider is
# wired into it) are intentionally absent rather than declared-and-never-emitted.
FleetOptimizeStatus = Literal[
    "SUCCESS",  # every trip assigned
    "PARTIAL",  # some trips assigned, others fit no vehicle
    "NO_FEASIBLE_SOLUTION",  # nothing could be assigned
    "NO_FEASIBLE_ASSIGNMENT",  # the selected compatible fleet cannot carry the load
    "MISSING_REQUIRED_DATA",  # capacity-constrained dispatch with unknown trip weight
    "MISSING_COST_DATA",  # monetary costing requested but a rate isn't configured
    "MISSING_HUB_DATA",  # hub-anchored routing requested but a vehicle has no hub
    "DRIVER_UNAVAILABLE",
    "VEHICLE_UNAVAILABLE",
    "CAPACITY_VIOLATION",
    "PICKUP_DROP_VIOLATION",
]


class FleetVehicleSelection(BaseModel):
    """The dispatcher picks WHICH vehicles and drivers are available; capacity,
    mileage, hub, and every cost rate are resolved server-side from the database
    (see dispatch_config_service) rather than trusted from the client - a client
    that could supply its own cost rates could silently skew the assignment."""

    vehicle_id: str
    driver_id: str | None = None


class OptimizeFleetRequest(BaseModel):
    stops: list[OptimizeStopInput]
    vehicles: list[FleetVehicleSelection]
    # Refuse rather than return a duration proxy when true - set this when the UI
    # intends to display currency (see cost_is_monetary below).
    require_monetary_cost: bool = False
    # Refuse rather than route hub-less when true.
    require_hub_routing: bool = False
    # Complete hub-to-hub duration hard limit. The operational default is 12 h.
    max_route_duration_seconds: float = 12 * 60 * 60


class FleetRouteMetrics(BaseModel):
    distance_meters: float
    duration_seconds: float
    fuel_liters: float
    fuel_cost: float
    driver_cost: float
    operating_cost: float
    fixed_cost: float
    peak_load_kg: float
    total_cost: float
    # False when no fuel data or cost rates were available and total_cost is a
    # duration proxy - callers must not render it as currency in that case.
    cost_is_monetary: bool


class FleetVehicleRouteOut(BaseModel):
    vehicle_id: str
    driver_id: str | None
    order: list[str]  # stop keys in visiting order
    trip_ids: list[str]
    metrics: FleetRouteMetrics


class OptimizeFleetResponse(BaseModel):
    status: FleetOptimizeStatus
    routes: list[FleetVehicleRouteOut]
    unassigned_trip_ids: list[str]
    totals: FleetRouteMetrics | None = None
    vehicles_used: int
    explanation: list[str]
    # Non-blocking advisories, e.g. trips dispatched with unrecorded weight.
    warnings: list[str] = []
    # Diagnostic information for unassigned trips
    unassigned_diagnostics: list[dict[str, Any]] = []