from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from src.models import delay_risk, eta_prediction, expected_delay, fuel_consumption, trip_cost
from src.optimizer import fleet, opt
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
    parent_trip_id: str | None = None
    original_load_weight_kg: float | None = None
    allowed_vehicle_ids: list[str] | None = None


class PickupDeliveryOptimizeRequest(BaseModel):
    jobs: list[OptimizeJob]
    duration_matrix: list[list[float]]
    distance_matrix: list[list[float]]
    coordinates: list[list[float]]  # [[lat, lon], ...], same index space as the matrices
    vehicle_capacity_kg: float | None = None
    # Cost-model weights (see src/optimizer/opt.py::CostWeights and WEIGHT_AWARE_ROUTING.md).
    # Defaults reduce the objective to plain duration - i.e. today's behavior - so callers that
    # don't send these are unaffected. When any of beta/gamma/delta is non-zero, terms are
    # baseline-normalized before being combined (see opt.compute_baselines) so these weights are
    # genuine relative-priority percentages, not a mix of raw seconds/meters/currency/tonne-km.
    alpha: float = 1.0  # duration
    beta: float = 0.0  # fuel cost - only consulted when non-zero AND avg_kmpl_rated/fuel_price_per_l given
    gamma: float = 0.0  # ton-km (load x distance)
    delta: float = 0.0  # distance
    avg_kmpl_rated: float | None = None
    fuel_price_per_l: float | None = None


class PickupDeliveryOptimizeResponse(BaseModel):
    order: list[int]  # matrix indices in optimized visiting order
    total_duration_seconds: float
    total_distance_meters: float
    solver_used: Literal["exact", "hybrid"]
    feasible: bool


# ---------------------------------------------------------------------------
# Multi-vehicle fleet optimization (see src/optimizer/fleet.py)
# ---------------------------------------------------------------------------

# Hard cap so a pathological request can't pin the solver - insertion search is
# O(vehicles x stops^2) per job, so cost grows fast. Well above any realistic
# dispatch batch for this product.
MAX_FLEET_JOBS = 60


class FleetVehicleInput(BaseModel):
    vehicle_id: str
    capacity_kg: float | None = None  # None => unconstrained
    avg_kmpl_rated: float | None = None
    fuel_price_per_l: float | None = None
    fixed_cost: float = 0.0
    driver_id: str | None = None
    # Optional depot/hub node indices into the same matrices the jobs index into.
    # Omit for an open route (today's behavior) - see MULTI_VEHICLE_ROUTING.md.
    start_idx: int | None = None
    end_idx: int | None = None
    # Per-vehicle rates; override the request-level fallbacks below.
    cost_per_km: float | None = None
    driver_cost_per_hour: float | None = None
    max_route_duration_seconds: float = 12 * 60 * 60


class FleetOptimizeRequest(BaseModel):
    jobs: list[OptimizeJob]
    vehicles: list[FleetVehicleInput]
    duration_matrix: list[list[float]]
    distance_matrix: list[list[float]]
    driver_cost_per_hour: float | None = None
    operating_cost_per_km: float | None = None
    iterations: int = 150
    seed: int | None = None


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
    cost_is_monetary: bool


class FleetVehicleRoute(BaseModel):
    vehicle_id: str
    driver_id: str | None
    order: list[int]  # job stops in visiting order (depot excluded)
    full_sequence: list[int]  # including depot start/end when configured
    trip_ids: list[str]
    metrics: FleetRouteMetrics


class FleetOptimizeResponse(BaseModel):
    status: Literal["SUCCESS", "PARTIAL", "NO_FEASIBLE_SOLUTION"]
    routes: list[FleetVehicleRoute]
    unassigned_trip_ids: list[str]
    totals: FleetRouteMetrics
    vehicles_used: int
    explanation: list[str]
    # Diagnostic information for unassigned trips
    unassigned_diagnostics: list[dict] = []


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
            parent_trip_id=j.parent_trip_id,
            original_load_weight_kg=j.original_load_weight_kg,
            allowed_vehicle_ids=frozenset(j.allowed_vehicle_ids) if j.allowed_vehicle_ids else None,
        )
        for j in request.jobs
    ]
    weights = opt.CostWeights(
        alpha=request.alpha,
        beta=request.beta,
        gamma=request.gamma,
        delta=request.delta,
        avg_kmpl_rated=request.avg_kmpl_rated,
        fuel_price_per_l=request.fuel_price_per_l,
    )
    try:
        result = hybrid_solve(
            jobs=jobs,
            duration_matrix=request.duration_matrix,
            distance_matrix=request.distance_matrix,
            coordinates=[tuple(c) for c in request.coordinates],
            vehicle_capacity_kg=request.vehicle_capacity_kg,
            weights=weights,
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


def _metrics_out(m: fleet.RouteMetrics) -> FleetRouteMetrics:
    return FleetRouteMetrics(
        distance_meters=m.distance_meters,
        duration_seconds=m.duration_seconds,
        fuel_liters=m.fuel_liters,
        fuel_cost=m.fuel_cost,
        driver_cost=m.driver_cost,
        operating_cost=m.operating_cost,
        fixed_cost=m.fixed_cost,
        peak_load_kg=m.peak_load_kg,
        total_cost=m.total_cost,
        cost_is_monetary=m.cost_is_monetary,
    )


def _diagnostic_out(d: fleet.TripAssignmentDiagnostic) -> dict:
    return {
        "trip_id": d.trip_id,
        "trip_weight_kg": d.trip_weight_kg,
        "status": d.status,
        "primary_failure_reason": d.primary_failure_reason,
        "capacity_failures": d.capacity_failures,
        "precedence_failures": d.precedence_failures,
        "total_positions_tested": d.total_positions_tested,
        "minimum_required_capacity_kg": d.minimum_required_capacity_kg,
        "vehicle_diagnostics": [
            {
                "vehicle_id": vd.vehicle_id,
                "vehicle_capacity_kg": vd.vehicle_capacity_kg,
                "current_peak_load_kg": vd.current_peak_load_kg,
                "static_remaining_capacity_kg": vd.static_remaining_capacity_kg,
                "capacity_failures": vd.capacity_failures,
                "precedence_failures": vd.precedence_failures,
                "feasible_insertions": vd.feasible_insertions,
                "best_peak_load_kg": vd.best_peak_load_kg,
                "best_incremental_cost": vd.best_incremental_cost,
                "best_pickup_position": vd.best_pickup_position,
                "best_delivery_position": vd.best_delivery_position,
                "total_pickup_positions_tested": vd.total_pickup_positions_tested,
                "total_delivery_positions_tested": vd.total_delivery_positions_tested,
            }
            for vd in d.vehicle_diagnostics
        ],
    }


@app.post("/optimize/fleet", response_model=FleetOptimizeResponse)
def optimize_fleet(request: FleetOptimizeRequest):
    """Assign jobs across a fleet AND sequence each vehicle's stops.

    Returns a typed status rather than failing: an instance where some job fits
    no vehicle is a legitimate business outcome (PARTIAL / NO_FEASIBLE_SOLUTION),
    not a server error. Capacity and pickup-before-delivery remain hard
    constraints enforced inside the solver via opt.route_is_feasible.
    """
    if len(request.jobs) > MAX_FLEET_JOBS:
        raise HTTPException(
            status_code=400,
            detail=f"Too many jobs for one fleet optimization: {len(request.jobs)} (max {MAX_FLEET_JOBS}).",
        )

    jobs = [
        opt.Job(
            trip_id=j.trip_id,
            pickup_idx=j.pickup_stop_index,
            delivery_idx=j.delivery_stop_index,
            load_weight_kg=j.load_weight_kg or 0.0,
            parent_trip_id=j.parent_trip_id,
            original_load_weight_kg=j.original_load_weight_kg,
            allowed_vehicle_ids=frozenset(j.allowed_vehicle_ids) if j.allowed_vehicle_ids else None,
        )
        for j in request.jobs
    ]
    vehicles = [
        fleet.FleetVehicle(
            vehicle_id=v.vehicle_id,
            capacity_kg=v.capacity_kg,
            avg_kmpl_rated=v.avg_kmpl_rated,
            fuel_price_per_l=v.fuel_price_per_l,
            fixed_cost=v.fixed_cost,
            driver_id=v.driver_id,
            start_idx=v.start_idx,
            end_idx=v.end_idx,
            cost_per_km=v.cost_per_km,
            driver_cost_per_hour=v.driver_cost_per_hour,
            max_route_duration_seconds=v.max_route_duration_seconds,
        )
        for v in request.vehicles
    ]
    rates = fleet.CostRates(
        driver_cost_per_hour=request.driver_cost_per_hour,
        operating_cost_per_km=request.operating_cost_per_km,
    )

    try:
        solution = fleet.fleet_solve(
            jobs=jobs,
            vehicles=vehicles,
            duration_matrix=request.duration_matrix,
            distance_matrix=request.distance_matrix,
            rates=rates,
            iterations=request.iterations,
            seed=request.seed,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    by_id = {v.vehicle_id: v for v in vehicles}
    if not solution.unassigned_trip_ids:
        status = "SUCCESS"
    elif solution.vehicles_used > 0:
        status = "PARTIAL"
    else:
        status = "NO_FEASIBLE_SOLUTION"

    return FleetOptimizeResponse(
        status=status,
        routes=[
            FleetVehicleRoute(
                vehicle_id=r.vehicle_id,
                driver_id=r.driver_id,
                order=r.route,
                full_sequence=r.full_sequence(by_id[r.vehicle_id]),
                trip_ids=r.trip_ids,
                metrics=_metrics_out(r.metrics),
            )
            for r in solution.routes
        ],
        unassigned_trip_ids=solution.unassigned_trip_ids,
        totals=_metrics_out(solution.totals),
        vehicles_used=solution.vehicles_used,
        explanation=fleet.explain_solution(solution, vehicles),
        unassigned_diagnostics=[_diagnostic_out(d) for d in solution.unassigned_diagnostics],
    )
