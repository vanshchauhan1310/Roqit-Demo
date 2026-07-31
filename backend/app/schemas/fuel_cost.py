from pydantic import BaseModel


class FuelCostEstimateRead(BaseModel):
    actual_fuel_liters: float | None = None  # real, only present once the trip has resolved (odometer/fuel log)
    ml_predicted_fuel_liters: float | None = None  # fuel_l_xgboost_v1.pkl
    heuristic_fuel_liters: float | None = None  # planned_distance_km / vehicle.avg_kmpl_rated
    estimated_cost_low: float | None = None
    estimated_cost_high: float | None = None


class TripCostPredictionRead(BaseModel):
    predicted_trip_cost: float
