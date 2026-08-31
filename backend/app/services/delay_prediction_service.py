import json
from pathlib import Path

import httpx
from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.models.delay_prediction import DelayPrediction
from app.models.trip import RESOLVED_STATUSES, DELAYED_STATUS, Trip
from app.services import ml_client
from app.services.weather_client import get_ml_weather_condition

MODEL_VERSION = "delay_risk_xgboost_v2"
FEATURE_CONTRACT_PATH = Path(__file__).resolve().parents[3] / "ml" / "feature_contract_v2.json"

# weather_condition is handled separately (live fetch with fallback to the stored
# value) rather than as a plain null-check, see engineer_features.
REQUIRED_TRIP_FIELDS = [
    "vehicle_type", "gps_start_lat", "gps_start_lon", "gps_end_lat", "gps_end_lon",
    "planned_distance_km", "road_type", "traffic_density",
    "fuel_price_per_l", "pickup_time", "planned_delivery_time",
]
REQUIRED_VEHICLE_FIELDS = ["fuel_type", "load_capacity_kg", "year"]
REQUIRED_DRIVER_FIELDS = ["license_type", "experience_years", "rating", "base_location"]

# (min, max) inclusive bounds for numeric features - mirrors the training
# notebook's own sanity-check discipline (lat in [-90,90], lon in [-180,180],
# speed >= 0, etc.), extended to this feature set. Fields not listed here
# have no enforced range beyond the null-check above.
NUMERIC_RANGES: dict[str, tuple[float, float]] = {
    "gps_start_lat": (-90, 90),
    "gps_end_lat": (-90, 90),
    "gps_start_lon": (-180, 180),
    "gps_end_lon": (-180, 180),
    "planned_distance_km": (0.01, 10000),
    "fuel_price_per_l": (0.01, 500),
    "planned_duration_hours": (0.01, 300),
    "planned_avg_speed_kmph": (0.01, 150),
    "experience_years": (0, 60),
    "rating": (0, 5),
    "load_capacity_kg": (1, 50000),
    "vehicle_age_years": (0, 50),
}


class MissingFeatureDataError(ValueError):
    """A required field is null - the record hasn't been fully onboarded."""


class UnsupportedCategoryError(ValueError):
    """A categorical value exists in Supabase but wasn't in the model's
    training vocabulary (see ml/feature_contract_v2.json). Distinct from
    MissingFeatureDataError because the fix is retraining, not data entry -
    per the training notebook's "flag anomalies, never silently hide them"
    discipline (e.g. a driver based in a city added after the model was
    trained)."""


class InvalidFeatureRangeError(ValueError):
    """A field is present and correctly typed, but its value is outside any
    physically plausible range (e.g. gps_start_lat=200, planned_distance_km=-50).
    Same "flag, don't silently fix" discipline as UnsupportedCategoryError -
    we refuse to predict on a value rather than clip/guess a corrected one."""


def _load_feature_contract() -> dict:
    with open(FEATURE_CONTRACT_PATH) as f:
        return json.load(f)


def _history_stats(db: Session, *filters) -> tuple[int, float]:
    """Trip counts/delay-rate as-of the current trip: prior RESOLVED trips
    only (status Delivered/Delayed - In-Transit/Cancelled excluded, they have
    no real delay outcome), matching the training notebook's time-aware
    "prior trips before this pickup_time" definition exactly."""
    prior = db.query(Trip.status).filter(and_(*filters), Trip.status.in_(RESOLVED_STATUSES)).all()
    count = len(prior)
    if count == 0:
        return 0, 0.0
    delay_rate = sum(1 for (status,) in prior if status == DELAYED_STATUS) / count
    return count, delay_rate


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
        if not (low <= features[field] <= high)
    ]
    if violations:
        raise InvalidFeatureRangeError(
            f"Trip has physically implausible values - refusing to predict: {violations}"
        )


async def engineer_features(db: Session, trip: Trip) -> dict:
    """Fetch Latest Trip -> Engineer Features: builds the exact 25-field
    payload ml/feature_contract_v2.json / delay_risk.predict() expects, from
    the real Supabase trips/driver_master/vehicle_master tables.

    weather_condition prefers a LIVE OpenWeather lookup at the trip's start
    coordinates over the stored column, falling back to the stored value if
    the live fetch is unavailable (no API key, provider error, missing GPS).
    """
    contract = _load_feature_contract()
    vocabulary = contract["categorical_vocabulary"]

    vehicle = trip.vehicle
    driver = trip.driver

    if vehicle is None:
        raise MissingFeatureDataError(
            f"Trip {trip.trip_id} has no assigned vehicle - assign it to a route before running delay prediction"
        )
    if driver is None:
        raise MissingFeatureDataError(
            f"Trip {trip.trip_id} has no assigned driver - assign it to a route before running delay prediction"
        )

    live_weather = await get_ml_weather_condition(trip.gps_start_lat, trip.gps_start_lon)
    weather_condition = live_weather or trip.weather_condition

    missing = [f for f in REQUIRED_TRIP_FIELDS if getattr(trip, f) is None]
    if weather_condition is None:
        missing.append("weather_condition")
    missing += [f"vehicle.{f}" for f in REQUIRED_VEHICLE_FIELDS if getattr(vehicle, f) is None]
    missing += [f"driver.{f}" for f in REQUIRED_DRIVER_FIELDS if getattr(driver, f) is None]
    if missing:
        raise MissingFeatureDataError(
            f"Trip {trip.trip_id} is missing required fields for delay prediction: {missing}"
        )

    planned_duration_hours = (trip.planned_delivery_time - trip.pickup_time).total_seconds() / 3600
    if planned_duration_hours <= 0:
        raise InvalidFeatureRangeError(
            f"Trip {trip.trip_id} has non-positive planned_duration_hours "
            f"({planned_duration_hours}) - check pickup_time/planned_delivery_time"
        )
    planned_avg_speed_kmph = trip.planned_distance_km / planned_duration_hours

    driver_trip_count_to_date, driver_delay_rate_to_date = _history_stats(
        db,
        Trip.driver_id == trip.driver_id,
        Trip.pickup_time < trip.pickup_time,
    )
    _, vehicle_delay_rate_to_date = _history_stats(
        db,
        Trip.vehicle_id == trip.vehicle_id,
        Trip.pickup_time < trip.pickup_time,
    )
    route_trip_count_to_date, route_delay_rate_to_date = _history_stats(
        db,
        Trip.origin == trip.origin,
        Trip.destination == trip.destination,
        Trip.pickup_time < trip.pickup_time,
    )

    features = {
        "vehicle_type": trip.vehicle_type,
        "gps_start_lat": trip.gps_start_lat,
        "gps_start_lon": trip.gps_start_lon,
        "gps_end_lat": trip.gps_end_lat,
        "gps_end_lon": trip.gps_end_lon,
        "planned_distance_km": trip.planned_distance_km,
        "weather_condition": weather_condition,
        "road_type": trip.road_type,
        "traffic_density": trip.traffic_density,
        "fuel_price_per_l": trip.fuel_price_per_l,
        "planned_duration_hours": planned_duration_hours,
        "planned_avg_speed_kmph": planned_avg_speed_kmph,
        "driver_trip_count_to_date": driver_trip_count_to_date,
        "driver_delay_rate_to_date": driver_delay_rate_to_date,
        "vehicle_delay_rate_to_date": vehicle_delay_rate_to_date,
        "route_trip_count_to_date": route_trip_count_to_date,
        "route_delay_rate_to_date": route_delay_rate_to_date,
        "has_route_history": route_trip_count_to_date > 0,
        "license_type": driver.license_type,
        "experience_years": driver.experience_years,
        "rating": driver.rating,
        "driver_base_location": driver.base_location,
        "fuel_type": vehicle.fuel_type,
        "load_capacity_kg": vehicle.load_capacity_kg,
        "vehicle_age_years": vehicle.vehicle_age_years,
    }

    for field in contract["categorical_features"]:
        _check_vocabulary(field, features[field], vocabulary)
    _check_ranges(features)

    return features


def store_prediction(
    db: Session, trip: Trip, features: dict, result: dict, model_version: str = MODEL_VERSION
) -> DelayPrediction:
    prediction = DelayPrediction(
        trip_id=trip.trip_id,
        delay_probability=result["delay_probability"],
        is_delayed_prediction=result["is_delayed_prediction"],
        model_version=model_version,
        features=features,
    )
    db.add(prediction)
    db.commit()
    db.refresh(prediction)
    return prediction


# Deterministic heuristic used when the ML service is unreachable - mirrors the
# ETA path's "ML first, rule-based fallback" pattern so the endpoint never 500s
# just because the model server is restarting.
_WEATHER_DELAY_RISK = {
    "Clear": 0.0, "Clouds": 0.02, "Extreme Heat": 0.08, "Drizzle": 0.08,
    "Rain": 0.15, "Storm": 0.25, "Thunderstorm": 0.25, "Snow": 0.3, "Fog": 0.18,
    "Mist": 0.1, "Haze": 0.12, "Dust": 0.12, "Sand": 0.12, "Squall": 0.25,
    "Tornado": 0.4,
}
_TRAFFIC_DELAY_RISK = {
    "Low": 0.0, "Medium": 0.08, "Moderate": 0.08, "High": 0.18, "Severe": 0.32,
}
_ROAD_DELAY_RISK = {
    "Highway": 0.0, "Expressway": 0.0, "City Road": 0.08, "Rural Road": 0.05,
    "State Road": 0.08, "Urban": 0.08, "Rural": 0.05, "Mountain": 0.12,
}
_WEATHER_DELAY_MINUTES = {
    "Clear": 0.0, "Clouds": 5.0, "Extreme Heat": 20.0, "Drizzle": 15.0,
    "Rain": 30.0, "Storm": 55.0, "Thunderstorm": 55.0, "Snow": 65.0, "Fog": 35.0,
    "Mist": 15.0, "Haze": 20.0, "Dust": 20.0, "Sand": 20.0, "Squall": 55.0,
    "Tornado": 90.0,
}
_TRAFFIC_DELAY_MINUTES = {
    "Low": 0.0, "Medium": 15.0, "Moderate": 15.0, "High": 35.0, "Severe": 60.0,
}


def _rule_based_delay_risk(features: dict) -> float:
    risk = 0.05
    risk += _WEATHER_DELAY_RISK.get(features.get("weather_condition"), 0.1)
    risk += _TRAFFIC_DELAY_RISK.get(features.get("traffic_density"), 0.05)
    risk += _ROAD_DELAY_RISK.get(features.get("road_type"), 0.05)
    if features.get("planned_distance_km", 0) > 1500:
        risk += 0.05
    risk += features.get("route_delay_rate_to_date", 0.0) * 0.15
    risk += features.get("driver_delay_rate_to_date", 0.0) * 0.1
    return round(min(max(risk, 0.01), 0.95), 4)


def _rule_based_expected_delay_minutes(features: dict) -> float:
    minutes = features.get("planned_duration_hours", 0.0) * 6
    minutes += _WEATHER_DELAY_MINUTES.get(features.get("weather_condition"), 20.0)
    minutes += _TRAFFIC_DELAY_MINUTES.get(features.get("traffic_density"), 10.0)
    minutes += features.get("route_delay_rate_to_date", 0.0) * 60
    return round(minutes, 1)


async def predict_delay_for_trip(db: Session, trip: Trip) -> DelayPrediction:
    """Engineer Features -> Load delay_model.pkl -> Predict -> Store Prediction.

    If the ML service is unreachable (restarting, connection dropped), falls
    back to a deterministic rule-based risk score rather than surfacing a 500.
    """
    features = await engineer_features(db, trip)
    try:
        result = await ml_client.predict_delay(features)
        model_version = MODEL_VERSION
    except httpx.HTTPError:
        result = {
            "delay_probability": _rule_based_delay_risk(features),
            "is_delayed_prediction": _rule_based_delay_risk(features) >= 0.5,
        }
        model_version = "rule_based_fallback"
    return store_prediction(db, trip, features, result, model_version)


async def predict_expected_delay_for_trip(db: Session, trip: Trip) -> dict:
    """Same feature pipeline as predict_delay_for_trip, but calls the expected-delay
    (minutes) regressor instead. Not persisted - this is a lighter-weight, display-only
    prediction rather than the audited DelayPrediction record."""
    features = await engineer_features(db, trip)
    try:
        return await ml_client.predict_expected_delay(features)
    except httpx.HTTPError:
        return {"predicted_delay_minutes": _rule_based_expected_delay_minutes(features)}
