from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from src.models import delay_risk, eta_prediction, expected_delay, fuel_consumption, trip_cost
from src.optimizer import opt
from src.optimizer.hybrid_solver import hybrid_solve

app = FastAPI(title="Fleet Optimization ML Service")


class EtaPredictionRequest(BaseModel):
    distance_km: float
    num_stops: int
    hour_of_day: int
    day_of_week: int
    avg_historical_speed_kph: float


class EtaPredictionResponse(BaseModel):
    predicted_duration_minutes: float


# Field order/types/categories mirror ml/feature_contract_v2.json exactly -
# keep the two in sync if the delay model is retrained on a new contract.
class DelayPredictionRequest(BaseModel):
    vehicle_type: Literal["Container Truck", "Mini Truck", "Refrigerated Truck", "Trailer", "Truck"]
    gps_start_lat: float
    gps_start_lon: float
    gps_end_lat: float
    gps_end_lon: float
    planned_distance_km: float
    weather_condition: Literal["Clear", "Extreme Heat", "Fog", "Rain", "Storm"]
    road_type: Literal["City Road", "Highway", "Rural Road", "State Road"]
    traffic_density: Literal["High", "Low", "Medium", "Severe"]
    fuel_price_per_l: float
    planned_duration_hours: float
    planned_avg_speed_kmph: float
    driver_trip_count_to_date: int
    driver_delay_rate_to_date: float
    vehicle_delay_rate_to_date: float
    route_trip_count_to_date: int
    route_delay_rate_to_date: float
    has_route_history: bool
    license_type: Literal["HMV", "HMV-Hazmat", "HMV-Trailer", "LMV"]
    experience_years: float
    rating: float
    driver_base_location: Literal[
        "Ahmedabad", "Bangalore", "Coimbatore", "Delhi", "Indore", "Jaipur",
        "Kolkata", "Mumbai", "Nagpur", "Pune", "Surat", "Vijayawada", "Visakhapatnam",
    ]
    fuel_type: Literal["CNG", "Diesel"]
    load_capacity_kg: float
    vehicle_age_years: float


class DelayPredictionResponse(BaseModel):
    delay_probability: float
    is_delayed_prediction: bool


class ExpectedDelayResponse(BaseModel):
    predicted_delay_minutes: float


# Field order/types/categories read directly off fuel_l_xgboost_v1.pkl /
# trip_cost_xgboost_v1.pkl's own trained booster metadata - both models share this
# 10-field schema (see build_features.COST_FEATURE_ORDER), distinct from delay's 25.
class CostPredictionRequest(BaseModel):
    vehicle_type: Literal["Container Truck", "Mini Truck", "Refrigerated Truck", "Trailer", "Truck"]
    road_type: Literal["City Road", "Highway", "Rural Road", "State Road"]
    traffic_density: Literal["High", "Low", "Medium", "Severe"]
    weather_condition: Literal["Clear", "Extreme Heat", "Fog", "Rain", "Storm"]
    fuel_type: Literal["CNG", "Diesel"]
    planned_distance_km: float
    load_weight_kg: int
    avg_kmpl_rated: float
    vehicle_age_years: int
    fuel_price_per_l: float


class FuelPredictionResponse(BaseModel):
    predicted_fuel_liters: float


class TripCostPredictionResponse(BaseModel):
    predicted_trip_cost: float


class OptimizeJob(BaseModel):
    trip_id: str
    pickup_stop_index: int
    delivery_stop_index: int
    load_weight_kg: float = 0.0


class PickupDeliveryOptimizeRequest(BaseModel):
    jobs: list[OptimizeJob]
    duration_matrix: list[list[float]]
    distance_matrix: list[list[float]]
    coordinates: list[list[float]]  # [[lat, lon], ...], same index space as the matrices
    vehicle_capacity_kg: float | None = None


class PickupDeliveryOptimizeResponse(BaseModel):
    order: list[int]  # matrix indices in optimized visiting order
    total_duration_seconds: float
    total_distance_meters: float
    solver_used: Literal["exact", "hybrid"]
    feasible: bool


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/predict/eta", response_model=EtaPredictionResponse)
def predict_eta(request: EtaPredictionRequest):
    try:
        duration = eta_prediction.predict(request.model_dump())
    except FileNotFoundError:
        raise HTTPException(status_code=503, detail="ETA model not trained yet. Run src/train.py --model eta first.")
    return EtaPredictionResponse(predicted_duration_minutes=duration)


@app.post("/predict/delay", response_model=DelayPredictionResponse)
def predict_delay(request: DelayPredictionRequest):
    try:
        result = delay_risk.predict(request.model_dump())
    except FileNotFoundError:
        raise HTTPException(
            status_code=503,
            detail="Delay model not found in models_store/. Run src/train.py --model delay first.",
        )
    return DelayPredictionResponse(**result)


# Same 25-field input as /predict/delay - both models share build_delay_features().
@app.post("/predict/expected-delay", response_model=ExpectedDelayResponse)
def predict_expected_delay(request: DelayPredictionRequest):
    try:
        result = expected_delay.predict(request.model_dump())
    except FileNotFoundError:
        raise HTTPException(
            status_code=503,
            detail="Expected-delay model not found in models_store/.",
        )
    return ExpectedDelayResponse(**result)


@app.post("/predict/fuel-liters", response_model=FuelPredictionResponse)
def predict_fuel_liters(request: CostPredictionRequest):
    try:
        result = fuel_consumption.predict(request.model_dump())
    except FileNotFoundError:
        raise HTTPException(status_code=503, detail="Fuel-consumption model not found in models_store/.")
    return FuelPredictionResponse(**result)


@app.post("/predict/trip-cost", response_model=TripCostPredictionResponse)
def predict_trip_cost(request: CostPredictionRequest):
    try:
        result = trip_cost.predict(request.model_dump())
    except FileNotFoundError:
        raise HTTPException(status_code=503, detail="Trip-cost model not found in models_store/.")
    return TripCostPredictionResponse(**result)


# No FileNotFoundError -> 503 handling here (unlike /predict/*): hybrid_solve
# degrades gracefully to the exact opt.solve() path when the .joblib ranking
# models haven't been trained yet (run src/optimizer/train_ml.py), rather than
# ever failing the request just because they're missing.
@app.post("/optimize/pickup-delivery", response_model=PickupDeliveryOptimizeResponse)
def optimize_pickup_delivery(request: PickupDeliveryOptimizeRequest):
    jobs = [
        opt.Job(
            trip_id=j.trip_id,
            pickup_idx=j.pickup_stop_index,
            delivery_idx=j.delivery_stop_index,
            load_weight_kg=j.load_weight_kg or 0.0,
        )
        for j in request.jobs
    ]
    try:
        result = hybrid_solve(
            jobs=jobs,
            duration_matrix=request.duration_matrix,
            distance_matrix=request.distance_matrix,
            coordinates=[tuple(c) for c in request.coordinates],
            vehicle_capacity_kg=request.vehicle_capacity_kg,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return PickupDeliveryOptimizeResponse(
        order=result.route,
        total_duration_seconds=result.total_duration_seconds,
        total_distance_meters=result.total_distance_meters,
        solver_used=result.solver_used,
        feasible=result.feasible,
    )
