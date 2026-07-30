from typing import Literal

from pydantic import BaseModel


class FuelCostEstimate(BaseModel):
    trip_id: str
    estimated_liters: float
    estimated_liters_source: Literal["actual", "ml_model", "heuristic"]

    price_low: float
    price_normal: float
    price_high: float

    cost_low: float
    cost_normal: float
    cost_high: float

    current_price_band: str | None = None
    current_cost: float | None = None

    sample_size: int
