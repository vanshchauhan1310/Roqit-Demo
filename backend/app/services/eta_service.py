from datetime import datetime, timedelta

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


async def predict_eta_for_trip(trip) -> dict:
    """Rule-based (NOT ML) ETA: real OSRM base duration, adjusted by a hand-coded
    weather multiplier at the trip's start coordinates.

    Distinct from /api/predictions/expected-delay, which is the ML regressor's
    prediction from the full 25-feature contract - this is the simpler,
    weather-rule-only estimate described as "weather_eta" in the architecture.
    """
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
