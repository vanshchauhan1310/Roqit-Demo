from typing import Literal

from pydantic import BaseModel


class OptimizeStopInput(BaseModel):
    key: str  # client-side stop identifier, echoed back in the optimized order
    latitude: float
    longitude: float
    trip_id: str
    stop_type: Literal["pickup", "delivery"]
    load_weight_kg: float | None = None  # meaningful on the pickup entry; ignored on delivery


class OptimizeRouteRequest(BaseModel):
    stops: list[OptimizeStopInput]
    vehicle_capacity_kg: float | None = None  # None => unconstrained (e.g. vehicle not chosen yet)


class OptimizeRouteResponse(BaseModel):
    order: list[str]  # stop keys in optimized visiting order
    total_duration_seconds: float
    total_distance_meters: float
    solver_used: Literal["exact", "hybrid"]
