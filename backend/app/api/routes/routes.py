import asyncio
import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.optimize import (
    OptimizeFleetRequest,
    OptimizeFleetResponse,
    OptimizeRouteRequest,
    OptimizeRouteResponse,
)
from app.schemas.route import (
    RouteAssignRequest,
    RouteAssignTrip,
    FleetPlanCreateRequest,
    RouteCreate,
    RouteRead,
    RouteReorderRequest,
    RouteStopCreate,
    RouteStopRead,
    RouteUpdateStatus,
)
from app.services import route_service
from app.services.route_optimizer import optimize_fleet, optimize_route

router = APIRouter(prefix="/routes", tags=["routes"])


@router.post("", response_model=RouteRead, status_code=201)
def create_route(route_in: RouteCreate, db: Session = Depends(get_db)):
    return route_service.create_route(db, route_in)


@router.get("", response_model=List[RouteRead])
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
    return await optimize_route(
        request.stops,
        request.vehicle_capacity_kg,
        avg_kmpl_rated=request.avg_kmpl_rated,
        fuel_price_per_l=request.fuel_price_per_l,
    )


@router.post("/optimize-fleet", response_model=OptimizeFleetResponse)
async def optimize_fleet_endpoint(request: OptimizeFleetRequest, db: Session = Depends(get_db)):
    """Multi-vehicle: assigns trips across a fleet and sequences each route.

    Additive to POST /routes/optimize, which stays the single-vehicle path and is
    unchanged. Business outcomes (a trip fitting no vehicle, missing weight on a
    capacity-constrained dispatch, unconfigured cost rates or hubs) come back as a
    typed `status` with HTTP 200; only genuine failures - bad input, upstream
    service down - use 4xx/5xx.
    """
    return await optimize_fleet(
        db,
        request.stops,
        request.vehicles,
        require_monetary_cost=request.require_monetary_cost,
        require_hub_routing=request.require_hub_routing,
        max_route_duration_seconds=request.max_route_duration_seconds,
    )


@router.post("/assign", response_model=RouteRead, status_code=201)
async def assign_route(assign_in: RouteAssignRequest, db: Session = Depends(get_db)):
    try:
        route = route_service.assign_route(db, assign_in)
    except route_service.InsufficientTripsError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except route_service.TripNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except route_service.LoadExceedsVehicleCapacityError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # Give every stop an ETA right away (first stop = pickup_time, then each
    # leg's real OSRM duration adjusted for weather), so the stops are never
    # eta-less after creation.
    route.weather_eta = await route_service.compute_weather_eta(db, route)
    # Propagate the route-level plan to the trips so the ML models have
    # planned_delivery_time (and thus planned_duration_hours) to predict from.
    route_service.propagate_planned_delivery_time(db, route, route.weather_eta)
    return route


@router.post("/fleet-plan", response_model=list[RouteRead], status_code=201)
async def create_fleet_plan(plan: FleetPlanCreateRequest, db: Session = Depends(get_db)):
    try:
        routes = route_service.create_fleet_plan_routes(db, plan)
        for route in routes:
            route.weather_eta = await route_service.compute_weather_eta(db, route)
            route_service.propagate_planned_delivery_time(db, route, route.weather_eta)
        return routes
    except route_service.TripNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except route_service.PrecedenceViolationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except route_service.LoadExceedsVehicleCapacityError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except route_service.DriverUnavailableError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except route_service.VehicleUnavailableError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.patch("/{route_id}/stops/reorder", response_model=RouteRead)
async def reorder_route_stops(route_id: uuid.UUID, reorder_in: RouteReorderRequest, db: Session = Depends(get_db)):
    route = route_service.get_route(db, route_id)
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")
    try:
        return route_service.reorder_stops(db, route, reorder_in.stop_ids)
    except route_service.StopSetMismatchError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except route_service.PrecedenceViolationError as exc:
        raise HTTPException(status_code=400, detail=f"Precedence violation for trip {exc.trip_id}: delivery cannot come before pickup")
    except route_service.LoadExceedsVehicleCapacityError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/{route_id}", response_model=RouteRead)
async def get_route(route_id: uuid.UUID, db: Session = Depends(get_db)):
    route = route_service.get_route(db, route_id)
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")
    await route_service.ensure_stop_coordinates(db, route)
    await route_service.ensure_stop_weather(db, route)
    route.weather_eta = await route_service.compute_weather_eta(db, route)
    route_service.propagate_planned_delivery_time(db, route, route.weather_eta)
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
