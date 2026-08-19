import json
from pathlib import Path

from app.models.trip import Trip
from app.services import ml_client
from app.services.weather_client import get_ml_weather_condition

FEATURE_CONTRACT_PATH = Path(__file__).resolve().parents[3] / "ml" / "feature_contract_v2.json"

# fuel_l_xgboost_v1.pkl / trip_cost_xgboost_v1.pkl's real trained schema (see
# ml/src/features/build_features.py::COST_FEATURE_ORDER) - a 10-field subset of
# the same trips/vehicle_master data delay_prediction_service reads.
REQUIRED_TRIP_FIELDS = ["vehicle_type", "road_type", "traffic_density", "planned_distance_km", "load_weight_kg", "fuel_price_per_l"]
REQUIRED_VEHICLE_FIELDS = ["fuel_type", "avg_kmpl_rated", "year"]

NUMERIC_RANGES: dict[str, tuple[float, float]] = {
    "planned_distance_km": (0.01, 10000),
    "load_weight_kg": (0, 50000),
    "avg_kmpl_rated": (0.1, 50),
    "vehicle_age_years": (0, 50),
    "fuel_price_per_l": (0.01, 500),
}


class MissingFeatureDataError(ValueError):
    """A required field is null - the record hasn't been fully onboarded."""


class UnsupportedCategoryError(ValueError):
    """A categorical value exists in Supabase but wasn't in the model's trained
    vocabulary. Same "flag, don't guess" discipline as delay_prediction_service."""


class InvalidFeatureRangeError(ValueError):
    """A field is present but outside any physically plausible range."""


def _load_feature_contract() -> dict:
    with open(FEATURE_CONTRACT_PATH) as f:
        return json.load(f)


def _check_vocabulary(field: str, value, vocabulary: dict) -> None:
    allowed = vocabulary.get(field)
    if allowed is not None and value not in allowed:
        raise UnsupportedCategoryError(
            f"{field}={value!r} is not in the model's trained vocabulary {allowed}. "
            "The model needs retraining to support this value - do not silently drop or remap it."
        )


def _check_ranges(features: dict) -> None:
    violations = [
        f"{field}={features[field]} outside plausible range [{low}, {high}]"
        for field, (low, high) in NUMERIC_RANGES.items()
        if features.get(field) is not None and not (low <= features[field] <= high)
    ]
    if violations:
        raise InvalidFeatureRangeError(f"Trip has physically implausible values - refusing to predict: {violations}")


async def build_cost_payload(trip: Trip) -> dict:
    """Builds the 10-field payload fuel_consumption/trip_cost expect. weather_condition
    prefers a LIVE OpenWeather lookup (same as delay_prediction_service), falling back
    to the trip's stored value."""
    contract = _load_feature_contract()
    vocabulary = contract["categorical_vocabulary"]

    vehicle = trip.vehicle
    if vehicle is None:
        raise MissingFeatureDataError(
            f"Trip {trip.trip_id} has no assigned vehicle - assign it to a route before running cost prediction"
        )

    live_weather = await get_ml_weather_condition(trip.gps_start_lat, trip.gps_start_lon)
    weather_condition = live_weather or trip.weather_condition

    missing = [f for f in REQUIRED_TRIP_FIELDS if getattr(trip, f) is None]
    if weather_condition is None:
        missing.append("weather_condition")
    missing += [f"vehicle.{f}" for f in REQUIRED_VEHICLE_FIELDS if getattr(vehicle, f) is None]
    if missing:
        raise MissingFeatureDataError(f"Trip {trip.trip_id} is missing required fields for cost prediction: {missing}")

    features = {
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

    for field in ("vehicle_type", "road_type", "traffic_density", "weather_condition", "fuel_type"):
        _check_vocabulary(field, features[field], vocabulary)
    _check_ranges(features)

    return features


async def predict_fuel_liters_for_trip(trip: Trip) -> dict:
    features = await build_cost_payload(trip)
    return await ml_client.predict_fuel_liters(features)


async def predict_trip_cost_for_trip(trip: Trip) -> dict:
    features = await build_cost_payload(trip)
    return await ml_client.predict_trip_cost(features)


# Cost-estimate uncertainty band applied around whichever liters figure is used
# (ML if available, else the heuristic) - not a modeled confidence interval, just
# a simple +/-10% spread so the UI can show a range rather than a false-precision point.
COST_RANGE_SPREAD = 0.1


async def get_fuel_cost_estimate(trip: Trip) -> dict:
    """Combines: the trip's real actual_fuel_liters (once resolved), the ML
    model's prediction, and a simple distance/rated-mileage heuristic - plus a
    cost range (liters x fuel_price_per_l, +/-10%) using whichever liters figure
    is available (ML preferred, heuristic as fallback)."""
    heuristic_fuel_liters = None
    vehicle = trip.vehicle
    if trip.planned_distance_km is not None and vehicle and vehicle.avg_kmpl_rated:
        heuristic_fuel_liters = trip.planned_distance_km / vehicle.avg_kmpl_rated

    ml_predicted_fuel_liters = None
    try:
        result = await predict_fuel_liters_for_trip(trip)
        ml_predicted_fuel_liters = result["predicted_fuel_liters"]
    except (MissingFeatureDataError, UnsupportedCategoryError, InvalidFeatureRangeError):
        pass  # fall back to the heuristic below; the caller can inspect the None to see ML wasn't available

    liters_for_cost = ml_predicted_fuel_liters if ml_predicted_fuel_liters is not None else heuristic_fuel_liters

    estimated_cost_low = estimated_cost_high = None
    if liters_for_cost is not None and trip.fuel_price_per_l is not None:
        base_cost = liters_for_cost * trip.fuel_price_per_l
        estimated_cost_low = base_cost * (1 - COST_RANGE_SPREAD)
        estimated_cost_high = base_cost * (1 + COST_RANGE_SPREAD)

    return {
        "actual_fuel_liters": trip.fuel_consumed_l,
        "ml_predicted_fuel_liters": ml_predicted_fuel_liters,
        "heuristic_fuel_liters": heuristic_fuel_liters,
        "estimated_cost_low": estimated_cost_low,
        "estimated_cost_high": estimated_cost_high,
    }
