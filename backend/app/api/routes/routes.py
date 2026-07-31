import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.optimize import OptimizeRouteRequest, OptimizeRouteResponse
from app.schemas.route import RouteAssignTrip, RouteCreate, RouteRead, RouteStopCreate, RouteStopRead, RouteUpdateStatus
from app.services import route_service
from app.services.route_optimizer import optimize_route

router = APIRouter(prefix="/routes", tags=["routes"])


@router.post("", response_model=RouteRead, status_code=201)
def create_route(route_in: RouteCreate, db: Session = Depends(get_db)):
    return route_service.create_route(db, route_in)


@router.get("", response_model=list[RouteRead])
async def list_routes(skip: int = 0, limit: int = 100, trip_id: str | None = None, db: Session = Depends(get_db)):
    routes = route_service.list_routes(db, skip, limit, trip_id)
    # Only backfill (geocode + weather) when scoped to a single trip's route — these hit
    # real external APIs per stop and are too expensive to run over an unfiltered, up-to-100-row list.
    if trip_id:
        for route in routes:
            await route_service.ensure_stop_coordinates(db, route)
            await route_service.ensure_stop_weather(db, route)
            route.weather_eta = await route_service.compute_weather_eta(db, route)
    return routes


@router.post("/optimize", response_model=OptimizeRouteResponse)
async def optimize(request: OptimizeRouteRequest):
    return await optimize_route(request.stops)


@router.get("/{route_id}", response_model=RouteRead)
async def get_route(route_id: uuid.UUID, db: Session = Depends(get_db)):
    route = route_service.get_route(db, route_id)
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")
    await route_service.ensure_stop_coordinates(db, route)
    await route_service.ensure_stop_weather(db, route)
    route.weather_eta = await route_service.compute_weather_eta(db, route)
    return route


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
