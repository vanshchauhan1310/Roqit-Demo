from typing import Any, Literal

from pydantic import BaseModel


class OptimizeStopInput(BaseModel):
    key: str  # client-side stop identifier, echoed back in the optimized order
    latitude: float
    longitude: float
    trip_id: str
    stop_type: Literal["pickup", "delivery"]
    load_weight_kg: float | None = None  # meaningful on the pickup entry; ignored on delivery
    # The cargo carried by this particular vehicle assignment.  For an ordinary
    # trip it is the same as load_weight_kg; for a split it is one reconciled
    # part, while original_load_weight_kg remains the source-of-record value.
    assigned_weight_kg: float | None = None
    # Set only for an optimizer-created part of an oversized consignment. The
    # original trip record and its original weight remain unchanged.
    parent_trip_id: str | None = None
    original_load_weight_kg: float | None = None
    allowed_vehicle_ids: list[str] | None = None
    # Splitting is opt-in.  A caller cannot turn an indivisible load into parts
    # merely by sending multiple pickup/delivery pairs.
    allow_split_loads: bool = False


class OptimizeRouteRequest(BaseModel):
    stops: list[OptimizeStopInput]
    vehicle_capacity_kg: float | None = None  # None => unconstrained (e.g. vehicle not chosen yet)
    # Optional vehicle economics for the weight-aware cost model (see route_optimizer.py and
    # WEIGHT_AWARE_ROUTING.md). Omitted/None => optimizer falls back to plain duration, exactly
    # today's behavior.
    avg_kmpl_rated: float | None = None
    fuel_price_per_l: float | None = None


class OptimizeRouteResponse(BaseModel):
    order: list[str]  # stop keys in optimized visiting order
    total_duration_seconds: float
    total_distance_meters: float
    solver_used: Literal["exact", "hybrid"]


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
    totals: FleetRouteMetrics
    vehicles_used: int
    explanation: list[str]
    # Non-blocking advisories, e.g. trips dispatched with unrecorded weight.
    warnings: list[str] = []
    # Diagnostic information for unassigned trips
    unassigned_diagnostics: list[dict[str, Any]] = []
