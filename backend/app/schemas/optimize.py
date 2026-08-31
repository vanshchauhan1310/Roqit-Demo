from typing import Literal

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