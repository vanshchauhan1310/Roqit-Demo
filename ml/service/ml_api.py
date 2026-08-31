from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from src.models import delay_risk, eta_prediction, expected_delay, fuel_consumption, trip_cost
from src.optimizer import opt
from src.optimizer.hybrid_solver import hybrid_solve
from src.optimizer.ml_windows import build_time_windows_for_jobs, optimize_with_ml_windows
from src.optimizer.or_tools_solver import (
    Vehicle,
    CostWeights,
    solve_with_fallback,
    OrToolsSolveResult,
)

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
    pickup_earliest: int | None = None
    pickup_latest: int | None = None
    delivery_earliest: int | None = None
    delivery_latest: int | None = None
    service_time_sec: int = 300


class OptimizeVehicle(BaseModel):
    vehicle_id: str
    capacity_kg: float
    start_location: int
    avg_kmpl_rated: float = 8.5
    fuel_price_per_l: float = 92.5
    duty_start: int | None = None
    duty_end: int | None = None


class CostWeightsRequest(BaseModel):
    alpha: float = 0.4   # duration weight
    delta: float = 0.2   # distance weight
    beta: float = 0.3    # fuel weight
    gamma: float = 0.1   # load (ton-km) weight
    lateness_weight: float = 60.0  # lateness penalty per second


class PickupDeliveryOptimizeRequest(BaseModel):
    jobs: list[OptimizeJob]
    vehicles: list[OptimizeVehicle]
    duration_matrix: list[list[float]]
    distance_matrix: list[list[float]]
    coordinates: list[list[float]]
    start_time: int = 0
    auto_generate_windows: bool = True
    vehicle_speed_kph: float = 40.0
    cost_weights: CostWeightsRequest | None = None
    solver_time_limit_seconds: int = 10


class VehicleRoute(BaseModel):
    vehicle_id: str
    stops: list[int]


class PickupDeliveryOptimizeResponse(BaseModel):
    routes: list[VehicleRoute]
    total_duration_seconds: float
    total_distance_meters: float
    total_lateness_seconds: float
    total_fuel_cost_rupees: float
    total_load_ton_km: float
    solver_used: Literal["or_tools", "fallback"]
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


@app.post("/optimize/pickup-delivery", response_model=PickupDeliveryOptimizeResponse)
def optimize_pickup_delivery(request: PickupDeliveryOptimizeRequest):
    jobs = [
        opt.Job(
            trip_id=j.trip_id,
            pickup_idx=j.pickup_stop_index,
            delivery_idx=j.delivery_stop_index,
            load_weight_kg=j.load_weight_kg or 0.0,
            pickup_earliest=j.pickup_earliest,
            pickup_latest=j.pickup_latest,
            delivery_earliest=j.delivery_earliest,
            delivery_latest=j.delivery_latest,
            service_time_sec=j.service_time_sec,
        )
        for j in request.jobs
    ]

    vehicles = [
        Vehicle(
            vehicle_id=v.vehicle_id,
            capacity_kg=v.capacity_kg,
            start_location=v.start_location,
            avg_kmpl_rated=v.avg_kmpl_rated,
            fuel_price_per_l=v.fuel_price_per_l,
            duty_start=v.duty_start,
            duty_end=v.duty_end,
        )
        for v in request.vehicles
    ]

    coordinates = [tuple(c) for c in request.coordinates]

    cost_weights = None
    if request.cost_weights:
        cost_weights = CostWeights(
            alpha=request.cost_weights.alpha,
            delta=request.cost_weights.delta,
            beta=request.cost_weights.beta,
            gamma=request.cost_weights.gamma,
            lateness_weight=request.cost_weights.lateness_weight,
        )

    try:
        if request.auto_generate_windows and request.start_time > 0:
            # Use ML ETA to auto-generate time windows
            enriched_jobs, _ = build_time_windows_for_jobs(
                jobs, coordinates, request.start_time, request.vehicle_speed_kph
            )
            result = solve_with_fallback(
                jobs=enriched_jobs,
                vehicles=vehicles,
                duration_matrix=request.duration_matrix,
                distance_matrix=request.distance_matrix,
                coordinates=coordinates,
                start_time=request.start_time,
                cost_weights=cost_weights,
                time_limit_seconds=request.solver_time_limit_seconds,
            )
        else:
            # Use provided windows (or none)
            result = solve_with_fallback(
                jobs=jobs,
                vehicles=vehicles,
                duration_matrix=request.duration_matrix,
                distance_matrix=request.distance_matrix,
                coordinates=coordinates,
                start_time=request.start_time,
                cost_weights=cost_weights,
                time_limit_seconds=request.solver_time_limit_seconds,
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    vehicle_routes = [
        VehicleRoute(vehicle_id=vid, stops=stops)
        for vid, stops in result.routes.items()
    ]

    return PickupDeliveryOptimizeResponse(
        routes=vehicle_routes,
        total_duration_seconds=result.total_duration_seconds,
        total_distance_meters=result.total_distance_meters,
        total_lateness_seconds=result.total_lateness_seconds,
        total_fuel_cost_rupees=result.total_fuel_cost_rupees,
        total_load_ton_km=result.total_load_ton_km,
        solver_used=result.solver_used,
        feasible=result.feasible,
    )