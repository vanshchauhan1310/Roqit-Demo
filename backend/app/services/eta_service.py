from datetime import datetime, timedelta

import httpx

from app.services import ml_client
from app.services.osrm_client import get_route_duration_hours
from app.services.weather_client import get_ml_weather_condition

# Hand-coded, rule-based weather delay multipliers applied on top of OSRM's
# baseline (no-traffic, no-weather) travel-time estimate. NOT learned from data -
# these are reasonable starting values (Rain/Storm per the original spec), the
# rest filled in for full vocabulary coverage. Tune freely if real ops data
# suggests different figures; keyed on the same 5-value vocabulary the delay/
# expected-delay ML models use, for consistency across the app.
WEATHER_ETA_MULTIPLIERS: dict[str, float] = {
    "Clear": 1.0,
    "Extreme Heat": 1.1,
    "Fog": 1.15,
    "Rain": 1.2,
    "Storm": 1.35,
}


async def compute_weather_adjusted_duration_hours(
    base_duration_hours: float, lat: float | None, lon: float | None
) -> dict:
    """Applies the hand-coded weather multiplier to an OSRM base duration."""
    condition = await get_ml_weather_condition(lat, lon)
    multiplier = WEATHER_ETA_MULTIPLIERS.get(condition, 1.0) if condition else 1.0
    return {
        "weather_condition": condition,
        "weather_multiplier": multiplier,
        "adjusted_duration_hours": base_duration_hours * multiplier,
    }


async def _base_duration_hours(
    start_lat: float | None,
    start_lon: float | None,
    end_lat: float | None,
    end_lon: float | None,
    fallback_distance_km: float | None,
) -> float | None:
    """Prefers a real OSRM route duration; falls back to a flat-speed estimate
    from planned_distance_km only if OSRM is unreachable or coordinates are missing."""
    if start_lat is not None and start_lon is not None and end_lat is not None and end_lon is not None:
        duration = await get_route_duration_hours(start_lat, start_lon, end_lat, end_lon)
        if duration is not None:
            return duration
    if fallback_distance_km is not None:
        return fallback_distance_km / 55  # rough flat-speed fallback, km/h
    return None


async def _ml_eta_duration_minutes(trip) -> float | None:
    """Calls the ML service's /predict/eta endpoint (RandomForest model). Returns
    None when the model isn't trained yet (503), the service is down, or the trip
    lacks the inputs, so the caller can fall back to the rule-based ETA."""
    if trip.planned_distance_km is None:
        return None
    try:
        result = await ml_client.predict_eta(
            {
                "distance_km": trip.planned_distance_km,
                "num_stops": trip.stop_count or 0,
                "hour_of_day": trip.pickup_time.hour if trip.pickup_time else 12,
                "day_of_week": trip.pickup_time.weekday() if trip.pickup_time else 0,
                "avg_historical_speed_kph": 55.0,
            }
        )
        return float(result["predicted_duration_minutes"])
    except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException, KeyError):
        return None


async def predict_eta_for_trip(trip) -> dict:
    """ETA for a trip: the ML model's duration prediction (minutes) when the model
    is available, otherwise a rule-based estimate - real OSRM base duration adjusted
    by a hand-coded weather multiplier at the trip's start coordinates.

    Distinct from /api/predictions/expected-delay, which is the ML regressor's
    prediction from the full 25-feature contract - this is the lighter-weight
    trip-duration ETA shown in the UI.
    """
    base_hours = None
    ml_duration_minutes = await _ml_eta_duration_minutes(trip)
    if ml_duration_minutes is not None:
        base_hours = ml_duration_minutes / 60
    else:
        base_hours = await _base_duration_hours(
            trip.gps_start_lat, trip.gps_start_lon, trip.gps_end_lat, trip.gps_end_lon, trip.planned_distance_km
        )

    if base_hours is None:
        return {
            "weather_condition": None,
            "weather_multiplier": None,
            "predicted_delivery_time": None,
            "expected_delay_minutes": None,
        }

    result = await compute_weather_adjusted_duration_hours(base_hours, trip.gps_start_lat, trip.gps_start_lon)

    predicted_delivery_time: datetime | None = None
    if trip.pickup_time:
        predicted_delivery_time = trip.pickup_time + timedelta(hours=result["adjusted_duration_hours"])

    expected_delay_minutes: float | None = None
    if trip.planned_delivery_time and predicted_delivery_time:
        expected_delay_minutes = (predicted_delivery_time - trip.planned_delivery_time).total_seconds() / 60

    return {
        "weather_condition": result["weather_condition"],
        "weather_multiplier": result["weather_multiplier"],
        "predicted_delivery_time": predicted_delivery_time,
        "expected_delay_minutes": expected_delay_minutes,
    }
