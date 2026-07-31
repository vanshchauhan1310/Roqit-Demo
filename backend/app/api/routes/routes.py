import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.route import Route
from app.schemas.optimize import OptimizeRouteRequest, OptimizeRouteResponse
from app.schemas.route import RouteAssignTrip, RouteCreate, RouteRead, RouteStopCreate, RouteStopRead, RouteUpdateStatus
from app.schemas.weather_eta import WeatherEtaEstimate
from app.services import eta_service, route_service
from app.services.route_optimizer import optimize_route

router = APIRouter(prefix="/routes", tags=["routes"])


async def _enrich_with_weather_eta(db: Session, route: Route) -> RouteRead:
    """Best-effort: attaches route-level weather_eta and per-stop eta
    timestamps. Falls back to the plain route (weather_eta=None, stop etas
    untouched) if weather/routing data isn't available - e.g. <2 geocoded
    stops, OPENWEATHER_API_KEY unset, or OSRM/OpenWeather unreachable."""
    route_data = RouteRead.model_validate(route)
    try:
        estimate, stop_etas, stop_weather, stop_statuses = await eta_service.estimate_weather_adjusted_eta(
            db, route.route_id
        )
    except (eta_service.InsufficientRouteDataError, HTTPException):
        return route_data

    route_data.weather_eta = estimate
    for stop in route_data.stops:
        if stop.stop_id in stop_etas:
            stop.eta = stop_etas[stop.stop_id]
        if stop.stop_id in stop_statuses:
            stop.computed_status = stop_statuses[stop.stop_id]
        weather = stop_weather.get(stop.stop_id)
        if weather:
            stop.weather_condition = weather["weather_condition"]
            stop.weather_description = weather["weather_description"]
            stop.temperature_c = weather["temperature_c"]
            stop.wind_speed_ms = weather["wind_speed_ms"]
    return route_data


@router.post("", response_model=RouteRead, status_code=201)
def create_route(route_in: RouteCreate, db: Session = Depends(get_db)):
    return route_service.create_route(db, route_in)


@router.get("", response_model=list[RouteRead])
async def list_routes(skip: int = 0, limit: int = 100, trip_id: str | None = None, db: Session = Depends(get_db)):
    routes = route_service.list_routes(db, skip, limit, trip_id)
    return await asyncio.gather(*(_enrich_with_weather_eta(db, route) for route in routes))


@router.post("/optimize", response_model=OptimizeRouteResponse)
async def optimize(request: OptimizeRouteRequest):
    return await optimize_route(request.stops)


@router.get("/{route_id}", response_model=RouteRead)
async def get_route(route_id: uuid.UUID, db: Session = Depends(get_db)):
    route = route_service.get_route(db, route_id)
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")
    return await _enrich_with_weather_eta(db, route)


@router.patch("/{route_id}/status", response_model=RouteRead)
def update_route_status(route_id: uuid.UUID, status_in: RouteUpdateStatus, db: Session = Depends(get_db)):
    route = route_service.get_route(db, route_id)
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")
    return route_service.update_route_status(db, route, status_in.status)


@router.patch("/{route_id}/trip", response_model=RouteRead)
def assign_trip(route_id: uuid.UUID, assign_in: RouteAssignTrip, db: Session = Depends(get_db)):
    route = route_service.get_route(db, route_id)
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")
    return route_service.assign_trip(db, route, assign_in.trip_id)


@router.post("/{route_id}/stops", response_model=RouteStopRead, status_code=201)
def add_stop(route_id: uuid.UUID, stop_in: RouteStopCreate, db: Session = Depends(get_db)):
    route = route_service.get_route(db, route_id)
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")
    return route_service.add_stop_to_route(db, route, stop_in)


@router.get("/{route_id}/weather-eta", response_model=WeatherEtaEstimate)
async def get_weather_eta(route_id: uuid.UUID, db: Session = Depends(get_db)):
    """Live weather at the route's origin stop (OpenWeather), used to adjust
    a base ETA (OSRM) up for rain/storm/fog/snow etc."""
    try:
        estimate, _, _, _ = await eta_service.estimate_weather_adjusted_eta(db, route_id)
        return estimate
    except eta_service.InsufficientRouteDataError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
