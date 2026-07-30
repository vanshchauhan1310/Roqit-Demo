from pydantic import BaseModel


class OptimizeStopInput(BaseModel):
    key: str  # client-side stop identifier, echoed back in the optimized order
    latitude: float
    longitude: float


class OptimizeRouteRequest(BaseModel):
    stops: list[OptimizeStopInput]  # stops[0] is treated as the fixed starting point


class OptimizeRouteResponse(BaseModel):
    order: list[str]  # stop keys in optimized visiting order (order[0] == stops[0].key)
    total_duration_seconds: float
    total_distance_meters: float
