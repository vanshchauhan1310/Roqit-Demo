import asyncio
import uuid
from datetime import datetime, timedelta
from math import atan2, cos, radians, sin, sqrt

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.gps_breadcrumb import GpsBreadcrumb
from app.models.route import RouteStop
from app.models.trip import Trip
from app.schemas.weather_eta import WeatherEtaEstimate
from app.services import route_service, weather_client

# A breadcrumb within this radius of a stop's coordinates counts as having
# arrived there - GPS drift/parking-lot-sized tolerance, not precision.
STOP_ARRIVAL_RADIUS_KM = 1.0

# OpenWeather's `weather[0].main` categories mapped to a duration multiplier.
# This is a coarse rule-based adjustment, not a trained-model vocabulary -
# there's no historical weather data to train the ETA model on, so an unseen
# condition defaults to 1.0 rather than erroring.
WEATHER_DELAY_MULTIPLIERS: dict[str, float] = {
    "Clear": 1.0,
    "Clouds": 1.0,
    "Drizzle": 1.1,
    "Rain": 1.2,
    "Thunderstorm": 1.35,
    "Snow": 1.4,
    "Mist": 1.2,
    "Fog": 1.2,
    "Haze": 1.2,
    "Smoke": 1.2,
    "Tornado": 1.5,
    "Squall": 1.5,
}
DEFAULT_WEATHER_MULTIPLIER = 1.0

StopWeather = dict[str, "str | float | None"]


class InsufficientRouteDataError(ValueError):
    """Fewer than 2 geocoded stops on the route - not enough to compute a base ETA."""


async def _fetch_osrm_route(stops: list[RouteStop]) -> tuple[float, float, list[float]]:
    """Returns (total_duration_minutes, total_distance_km, leg_durations_minutes)
    for the ordered stop path - one leg per consecutive stop pair, used to
    derive a per-stop arrival time, not just a single route-level total."""
    coords = ";".join(f"{s.longitude},{s.latitude}" for s in stops)
    url = f"{settings.OSRM_BASE_URL}/route/v1/driving/{coords}?overview=false"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url)
    except httpx.HTTPError as exc:
        # Network-level failure (timeout, DNS, connection refused) - not an
        # HTTP status, so it wouldn't otherwise be caught by callers that
        # only handle HTTPException from a bad response.
        raise HTTPException(status_code=502, detail=f"Routing provider unreachable: {exc}") from exc

    if response.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Routing provider returned {response.status_code}")

    routes = response.json().get("routes")
    if not routes:
        raise HTTPException(status_code=502, detail="Routing provider returned no route")

    route = routes[0]
    leg_durations_minutes = [leg["duration"] / 60 for leg in route.get("legs", [])]
    return route["duration"] / 60, route["distance"] / 1000, leg_durations_minutes


def _weather_summary(weather: dict) -> StopWeather:
    return {
        "weather_condition": weather["weather"][0]["main"],
        "weather_description": weather["weather"][0]["description"],
        "temperature_c": weather.get("main", {}).get("temp"),
        "wind_speed_ms": weather.get("wind", {}).get("speed"),
    }


async def _fetch_all_stop_weather(stops: list[RouteStop]) -> dict[uuid.UUID, StopWeather]:
    """Live weather at every stop, fetched concurrently. A single stop's
    provider failure doesn't take down the others - that stop is just left
    out of the result (its ETA leg falls back to the default multiplier)."""

    async def fetch(stop: RouteStop) -> tuple[uuid.UUID, StopWeather | None]:
        try:
            weather = await weather_client.get_current_weather(stop.latitude, stop.longitude)
        except HTTPException:
            return stop.stop_id, None
        return stop.stop_id, _weather_summary(weather)

    results = await asyncio.gather(*(fetch(s) for s in stops))
    return {stop_id: summary for stop_id, summary in results if summary is not None}


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius_km = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * earth_radius_km * atan2(sqrt(a), sqrt(1 - a))


def _infer_stop_statuses(
    stops: list[RouteStop],
    breadcrumbs: list[GpsBreadcrumb],
    stop_etas: dict[uuid.UUID, datetime],
    now: datetime,
) -> dict[uuid.UUID, str]:
    """Derived from real data, not a stored field - nothing in this codebase
    ever sets RouteStop.status today, so it would otherwise always read
    "pending". "completed" if a GPS breadcrumb was recorded within
    STOP_ARRIVAL_RADIUS_KM of the stop; "delayed" if we're past its computed
    ETA without arriving; else "pending"."""
    statuses: dict[uuid.UUID, str] = {}
    for stop in stops:
        arrived = any(
            b.lat is not None
            and b.lon is not None
            and _haversine_km(stop.latitude, stop.longitude, b.lat, b.lon) <= STOP_ARRIVAL_RADIUS_KM
            for b in breadcrumbs
        )
        if arrived:
            statuses[stop.stop_id] = "completed"
        elif stop.stop_id in stop_etas and now > stop_etas[stop.stop_id]:
            statuses[stop.stop_id] = "delayed"
        else:
            statuses[stop.stop_id] = "pending"
    return statuses


def _stop_arrival_times(
    stops: list[RouteStop],
    leg_durations_minutes: list[float],
    stop_weather: dict[uuid.UUID, StopWeather],
    start_time: datetime,
) -> dict[uuid.UUID, datetime]:
    """Cumulative arrival time at each stop: the first stop is the start_time
    itself (pickup); each subsequent leg is adjusted by the weather at the
    stop it arrives at (falls back to no adjustment if that stop's weather
    couldn't be fetched)."""
    arrivals: dict[uuid.UUID, datetime] = {stops[0].stop_id: start_time}
    cumulative_minutes = 0.0
    for stop, leg_minutes in zip(stops[1:], leg_durations_minutes):
        weather = stop_weather.get(stop.stop_id)
        condition = weather["weather_condition"] if weather else None
        multiplier = WEATHER_DELAY_MULTIPLIERS.get(condition, DEFAULT_WEATHER_MULTIPLIER)
        cumulative_minutes += leg_minutes * multiplier
        arrivals[stop.stop_id] = start_time + timedelta(minutes=cumulative_minutes)
    return arrivals


async def estimate_weather_adjusted_eta(
    db: Session, route_id: uuid.UUID
) -> tuple[WeatherEtaEstimate, dict[uuid.UUID, datetime], dict[uuid.UUID, StopWeather], dict[uuid.UUID, str]]:
    """Coordinates from GET /api/routes/{route_id} -> live weather at every
    stop (OpenWeather) -> weather-adjusted ETA on top of an OSRM base duration
    (the ML ETA model has no trained artifact yet, see ml/models_store/).
    Returns the route-level estimate (origin weather), a per-stop
    arrival-time map, a per-stop weather map, and a per-stop inferred status
    map (completed/delayed/pending, derived from real GPS breadcrumbs)."""
    route = route_service.get_route(db, route_id)
    if route is None:
        raise HTTPException(status_code=404, detail="Route not found")

    stops = sorted(
        (s for s in route.stops if s.latitude is not None and s.longitude is not None),
        key=lambda s: s.sequence or 0,
    )
    if len(stops) < 2:
        raise InsufficientRouteDataError(
            f"Route {route.route_id} has fewer than 2 stops with coordinates - cannot compute a base ETA"
        )

    base_duration_minutes, distance_km, leg_durations_minutes = await _fetch_osrm_route(stops)
    stop_weather = await _fetch_all_stop_weather(stops)

    origin = stops[0]
    origin_weather = stop_weather.get(origin.stop_id)
    if origin_weather is None:
        raise HTTPException(status_code=502, detail="Weather provider returned no data for the route origin")
    origin_multiplier = WEATHER_DELAY_MULTIPLIERS.get(origin_weather["weather_condition"], DEFAULT_WEATHER_MULTIPLIER)

    trip = db.get(Trip, route.trip_id) if route.trip_id else None
    start_time = (trip.pickup_time if trip and trip.pickup_time else None) or datetime.utcnow()
    stop_etas = _stop_arrival_times(stops, leg_durations_minutes, stop_weather, start_time)

    breadcrumbs = (
        db.query(GpsBreadcrumb).filter(GpsBreadcrumb.trip_id == route.trip_id).all() if route.trip_id else []
    )
    stop_statuses = _infer_stop_statuses(stops, breadcrumbs, stop_etas, datetime.utcnow())

    estimate = WeatherEtaEstimate(
        route_id=route.route_id,
        origin_latitude=origin.latitude,
        origin_longitude=origin.longitude,
        weather_condition=origin_weather["weather_condition"],
        weather_description=origin_weather["weather_description"],
        temperature_c=origin_weather["temperature_c"],
        wind_speed_ms=origin_weather["wind_speed_ms"],
        distance_km=round(distance_km, 2),
        base_duration_minutes=round(base_duration_minutes, 1),
        weather_delay_multiplier=origin_multiplier,
        adjusted_duration_minutes=round(base_duration_minutes * origin_multiplier, 1),
    )
    return estimate, stop_etas, stop_weather, stop_statuses
