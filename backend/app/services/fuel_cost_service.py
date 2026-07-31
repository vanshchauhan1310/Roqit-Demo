import httpx
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.trip import Trip
from app.models.vehicle import Vehicle
from app.schemas.fuel_cost import FuelCostEstimate
from app.schemas.trip_cost import TripCostEstimate
from app.services import ml_client, weather_client


class InsufficientHistoryError(ValueError):
    """No historical fuel_price_per_l data exists yet - refuse to guess quantiles."""


class MissingFuelInputError(ValueError):
    """None of the actual/ML/heuristic paths can produce a liters estimate -
    see estimate_liters."""


class MissingCostInputError(ValueError):
    """Trip/vehicle is missing one of the 10 fields the trip-cost model needs.
    No heuristic fallback exists for total cost - this one's ML-only."""


async def _build_cost_payload(trip: Trip, vehicle: Vehicle) -> dict | None:
    """The 10-field payload fuel_l_xgboost_v1.pkl and trip_cost_xgboost_v1.pkl
    both expect (see ml/src/features/build_features.py::COST_FEATURE_ORDER).
    weather_condition is live (OpenWeather at the trip's start coordinates,
    mapped onto the trained vocabulary), falling back to the trip's stored
    value if the live lookup fails. Returns None if any field is still
    missing - callers decide whether to fall back or refuse to predict."""
    weather_condition = await weather_client.get_ml_weather_condition(
        trip.gps_start_lat, trip.gps_start_lon
    ) or trip.weather_condition

    payload = {
        "vehicle_type": trip.vehicle_type,
        "road_type": trip.road_type,
        "traffic_density": trip.traffic_density,
        "weather_condition": weather_condition,
        "fuel_type": vehicle.fuel_type,
        "planned_distance_km": trip.planned_distance_km,
        "load_weight_kg": trip.load_weight_kg,
        "avg_kmpl_rated": vehicle.avg_kmpl_rated,
        "vehicle_age_years": vehicle.vehicle_age_years,
        "fuel_price_per_l": trip.fuel_price_per_l,
    }
    if any(value is None for value in payload.values()):
        return None
    return payload


def get_price_quantiles(db: Session) -> tuple[float, float, float, float, float, int]:
    """10th/33rd/50th/67th/90th percentiles of historical fuel_price_per_l,
    plus the sample size they were computed from. p10/p50/p90 are the
    low/normal/high scenario prices; p33/p67 are the cutoffs used to classify
    a trip's own current price into one of those three bands."""
    count = db.query(func.count(Trip.fuel_price_per_l)).filter(Trip.fuel_price_per_l.isnot(None)).scalar()
    if not count:
        raise InsufficientHistoryError("No historical fuel_price_per_l data available to compute quantiles")

    p10, p33, p50, p67, p90 = (
        db.query(
            func.percentile_cont(0.10).within_group(Trip.fuel_price_per_l),
            func.percentile_cont(0.33).within_group(Trip.fuel_price_per_l),
            func.percentile_cont(0.50).within_group(Trip.fuel_price_per_l),
            func.percentile_cont(0.67).within_group(Trip.fuel_price_per_l),
            func.percentile_cont(0.90).within_group(Trip.fuel_price_per_l),
        )
        .filter(Trip.fuel_price_per_l.isnot(None))
        .one()
    )
    return p10, p33, p50, p67, p90, count


async def estimate_liters(trip: Trip, vehicle: Vehicle) -> tuple[float, str]:
    """Returns (liters, source). Prefers the trip's actual fuel_consumed_l,
    then the trained fuel_l_xgboost_v1.pkl model (factors in road type,
    traffic, weather, load), then falls back to a simple distance/kmpl
    heuristic if the ML fields aren't all available."""
    if trip.fuel_consumed_l is not None:
        return trip.fuel_consumed_l, "actual"

    payload = await _build_cost_payload(trip, vehicle)
    if payload is not None:
        try:
            result = await ml_client.predict_fuel_liters(payload)
            return result["predicted_fuel_liters"], "ml_model"
        except httpx.HTTPStatusError:
            pass  # ML service unavailable/model missing - fall through to the heuristic

    if trip.planned_distance_km is not None and vehicle.avg_kmpl_rated:
        return trip.planned_distance_km / vehicle.avg_kmpl_rated, "heuristic"

    raise MissingFuelInputError(
        f"Trip {trip.trip_id} has no fuel_consumed_l and cannot derive it from "
        "the fuel-liters ML model or planned_distance_km/vehicle.avg_kmpl_rated"
    )


def _price_band(price: float, p33: float, p67: float) -> str:
    if price <= p33:
        return "low"
    if price >= p67:
        return "high"
    return "normal"


async def estimate_fuel_cost_range(db: Session, trip: Trip, vehicle: Vehicle) -> FuelCostEstimate:
    p10, p33, p50, p67, p90, sample_size = get_price_quantiles(db)
    liters, liters_source = await estimate_liters(trip, vehicle)

    current_price_band = None
    current_cost = None
    if trip.fuel_price_per_l is not None:
        current_price_band = _price_band(trip.fuel_price_per_l, p33, p67)
        current_cost = round(trip.fuel_price_per_l * liters, 2)

    return FuelCostEstimate(
        trip_id=trip.trip_id,
        estimated_liters=round(liters, 2),
        estimated_liters_source=liters_source,
        price_low=round(p10, 2),
        price_normal=round(p50, 2),
        price_high=round(p90, 2),
        cost_low=round(p10 * liters, 2),
        cost_normal=round(p50 * liters, 2),
        cost_high=round(p90 * liters, 2),
        current_price_band=current_price_band,
        current_cost=current_cost,
        sample_size=sample_size,
    )


async def estimate_trip_cost(trip: Trip, vehicle: Vehicle) -> TripCostEstimate:
    payload = await _build_cost_payload(trip, vehicle)
    if payload is None:
        raise MissingCostInputError(
            f"Trip {trip.trip_id} is missing one of the fields the trip-cost model needs: "
            "vehicle_type, road_type, traffic_density, weather_condition, fuel_type, "
            "planned_distance_km, load_weight_kg, avg_kmpl_rated, vehicle_age_years, fuel_price_per_l"
        )

    result = await ml_client.predict_trip_cost(payload)
    return TripCostEstimate(trip_id=trip.trip_id, predicted_trip_cost=round(result["predicted_trip_cost"], 2))
