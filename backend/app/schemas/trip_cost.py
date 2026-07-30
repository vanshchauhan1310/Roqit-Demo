from pydantic import BaseModel


class TripCostEstimate(BaseModel):
    trip_id: str
    predicted_trip_cost: float
