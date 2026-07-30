from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from src.models import delay_risk, eta_prediction, expected_delay, fuel_consumption, trip_cost

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
    expected_delay_minutes: float


# Shared by /predict/fuel-liters and /predict/trip-cost - both models were
# trained on the same 10-field feature set.
class CostFeaturesRequest(BaseModel):
    vehicle_type: Literal["Container Truck", "Mini Truck", "Refrigerated Truck", "Trailer", "Truck"]
    road_type: Literal["City Road", "Highway", "Rural Road", "State Road"]
    traffic_density: Literal["High", "Low", "Medium", "Severe"]
    weather_condition: Literal["Clear", "Extreme Heat", "Fog", "Rain", "Storm"]
    fuel_type: Literal["CNG", "Diesel"]
    planned_distance_km: float
    load_weight_kg: float
    avg_kmpl_rated: float
    vehicle_age_years: float
    fuel_price_per_l: float


class FuelLitersResponse(BaseModel):
    predicted_fuel_liters: float


class TripCostResponse(BaseModel):
    predicted_trip_cost: float


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


@app.post("/predict/expected-delay", response_model=ExpectedDelayResponse)
def predict_expected_delay(request: DelayPredictionRequest):
    try:
        minutes = expected_delay.predict(request.model_dump())
    except FileNotFoundError:
        raise HTTPException(
            status_code=503, detail="Expected-delay model not found in models_store/."
        )
    return ExpectedDelayResponse(expected_delay_minutes=minutes)


@app.post("/predict/fuel-liters", response_model=FuelLitersResponse)
def predict_fuel_liters(request: CostFeaturesRequest):
    try:
        liters = fuel_consumption.predict(request.model_dump())
    except FileNotFoundError:
        raise HTTPException(status_code=503, detail="Fuel-consumption model not found in models_store/.")
    return FuelLitersResponse(predicted_fuel_liters=liters)


@app.post("/predict/trip-cost", response_model=TripCostResponse)
def predict_trip_cost(request: CostFeaturesRequest):
    try:
        cost = trip_cost.predict(request.model_dump())
    except FileNotFoundError:
        raise HTTPException(status_code=503, detail="Trip-cost model not found in models_store/.")
    return TripCostResponse(predicted_trip_cost=cost)
