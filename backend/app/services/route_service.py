import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.route import Route, RouteStop
from app.models.trip import Trip
from app.schemas.route import RouteCreate, RouteStopCreate
from app.services.eta_service import WEATHER_ETA_MULTIPLIERS
from app.services.geocode_client import geocode_address
from app.services.osrm_client import get_route_duration_hours
from app.services.weather_client import fetch_weather, map_condition_to_ml_vocabulary

# Cached per-stop weather is refetched once it's older than this.
WEATHER_STALE_AFTER = timedelta(hours=1)


def create_route(db: Session, route_in: RouteCreate) -> Route:
    route = Route(trip_id=route_in.trip_id, name=route_in.name)
    db.add(route)
    db.flush()

    for position, stop_in in enumerate(route_in.stops, start=1):
        stop_data = stop_in.model_dump()
        if stop_data.get("sequence") is None:
            stop_data["sequence"] = position
        db.add(RouteStop(route_id=route.route_id, **stop_data))

    db.commit()
    db.refresh(route)
    return route


def get_route(db: Session, route_id: uuid.UUID) -> Route | None:
    return db.get(Route, route_id)


def list_routes(db: Session, skip: int = 0, limit: int = 100, trip_id: str | None = None) -> list[Route]:
    query = db.query(Route)
    if trip_id:
        query = query.filter(Route.trip_id == trip_id)
    return query.order_by(Route.created_at.desc()).offset(skip).limit(limit).all()


def update_route_status(db: Session, route: Route, status: str) -> Route:
    route.status = status
    db.add(route)
    db.commit()
    db.refresh(route)
    return route


def assign_trip(db: Session, route: Route, trip_id: str) -> Route:
    route.trip_id = trip_id
    db.add(route)
    db.commit()
    db.refresh(route)
    return route


async def ensure_stop_coordinates(db: Session, route: Route) -> bool:
    """Lazily backfills lat/lon for any stop that has an address but no coordinates yet
    (e.g. routes seeded from historical trips, or added without using the Locate button).

    Self-healing on first read, same pattern as the trip auto-status-transition —
    once a stop is geocoded and committed, it's never re-geocoded.
    """
    changed = False
    for stop in route.stops:
        if stop.latitude is not None or stop.longitude is not None or not stop.address:
            continue
        try:
            result = await geocode_address(stop.address)
        except Exception:
            continue
        stop.latitude = result.lat
        stop.longitude = result.lng
        db.add(stop)
        changed = True
        await asyncio.sleep(1)  # respect Nominatim's ~1 request/second usage policy

    if changed:
        db.commit()
        db.refresh(route)
    return changed


async def _refresh_stop_weather(stop: RouteStop, now: datetime) -> bool:
    try:
        result = await fetch_weather(stop.latitude, stop.longitude)
    except Exception:
        return False
    stop.weather_condition = result.condition
    stop.weather_updated_at = now
    return True


async def ensure_stop_weather(db: Session, route: Route) -> bool:
    """Lazily (re)fetches per-stop weather for any geocoded stop whose cached weather
    is missing or older than WEATHER_STALE_AFTER. Persisted on route_stops so repeat
    reads within the hour don't re-hit OpenWeather. Unlike Nominatim, OpenWeather has
    no 1 req/sec restriction, so stale stops are refreshed concurrently.
    """
    now = datetime.now(timezone.utc)
    stale_stops = [
        stop
        for stop in route.stops
        if stop.latitude is not None
        and stop.longitude is not None
        and (stop.weather_updated_at is None or now - stop.weather_updated_at >= WEATHER_STALE_AFTER)
    ]
    if not stale_stops:
        return False

    results = await asyncio.gather(*(_refresh_stop_weather(stop, now) for stop in stale_stops))
    changed = any(results)
    for stop in stale_stops:
        db.add(stop)

    if changed:
        db.commit()
        db.refresh(route)
    return changed


async def compute_weather_eta(db: Session, route: Route) -> datetime | None:
    """Rule-based, NOT ML: walks the route's geocoded stops in sequence, computing
    each leg's real OSRM duration adjusted by that leg's destination-stop weather
    (via eta_service's hand-coded multiplier table), starting from the linked
    trip's pickup_time. Persists each stop's `eta` column so it doesn't get
    recomputed on every read. Returns the final stop's ETA (the route-level
    "weather_eta"), or None if there's no linked trip/pickup_time or fewer than
    2 geocoded stops.
    """
    if not route.trip_id:
        return None
    trip = db.get(Trip, route.trip_id)
    if not trip or not trip.pickup_time:
        return None

    stops = sorted(route.stops, key=lambda s: s.sequence)
    geocoded = [s for s in stops if s.latitude is not None and s.longitude is not None]
    if len(geocoded) < 2:
        return None

    current_time = trip.pickup_time
    changed = False

    for prev, stop in zip(geocoded, geocoded[1:]):
        base_hours = await get_route_duration_hours(prev.latitude, prev.longitude, stop.latitude, stop.longitude)
        if base_hours is None:
            base_hours = 0.0

        ml_condition = map_condition_to_ml_vocabulary(stop.weather_condition) if stop.weather_condition else None
        multiplier = WEATHER_ETA_MULTIPLIERS.get(ml_condition, 1.0) if ml_condition else 1.0

        current_time = current_time + timedelta(hours=base_hours * multiplier)
        if stop.eta != current_time:
            stop.eta = current_time
            db.add(stop)
            changed = True

    if changed:
        db.commit()
        db.refresh(route)

    return geocoded[-1].eta


def add_stop_to_route(db: Session, route: Route, stop_in: RouteStopCreate) -> RouteStop:
    stop_data = stop_in.model_dump()

    if stop_data.get("sequence") is None:
        max_sequence = db.query(func.max(RouteStop.sequence)).filter(RouteStop.route_id == route.route_id).scalar()
        stop_data["sequence"] = (max_sequence or 0) + 1

    stop = RouteStop(route_id=route.route_id, **stop_data)
    db.add(stop)
    db.commit()
    db.refresh(stop)
    return stop
