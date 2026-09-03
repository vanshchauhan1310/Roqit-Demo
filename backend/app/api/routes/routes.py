import asyncio
import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.optimization_audit import OptimizationRun
from app.schemas.optimize import OptimizeFleetRequest, OptimizeFleetResponse, OptimizeRouteRequest, OptimizeRouteResponse
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
from app.services import ml_client, route_service
from app.services.route_optimizer import optimize_route
from app.workers.lns_worker import create_lns_job, lns_worker

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
        request.vehicles,
        request.vehicle_capacity_kg,
        request.auto_generate_windows,
        request.start_time,
        request.vehicle_speed_kph,
        request.cost_weights,
        request.solver_time_limit_seconds,
        request.depot,
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
    from app.services import dispatch_config_service
    from app.models.vehicle import Vehicle
    from app.models.driver import Driver
    from app.schemas.optimize import OptimizeVehicleInput, CostWeightsInput
    import httpx

    # Resolve vehicle/driver details and cost rates from database
    vehicle_ids = [v.vehicle_id for v in request.vehicles]
    driver_ids = [v.driver_id for v in request.vehicles if v.driver_id]
    
    vehicles_db = db.query(Vehicle).filter(Vehicle.vehicle_id.in_(vehicle_ids)).all()
    drivers_db = db.query(Driver).filter(Driver.driver_id.in_(driver_ids)).all() if driver_ids else []
    
    vehicles_map = {v.vehicle_id: v for v in vehicles_db}
    drivers_map = {d.driver_id: d for d in drivers_db}
    
    # Build vehicle input with cost rates from dispatch config
    vehicle_inputs = []
    cost_config = dispatch_config_service.get_cost_config(db)
    hub_config = dispatch_config_service.get_hub_config(db)
    
    for v_req in request.vehicles:
        vehicle = vehicles_map.get(v_req.vehicle_id)
        if not vehicle:
            return OptimizeFleetResponse(
                status="VEHICLE_UNAVAILABLE",
                routes=[],
                unassigned_trip_ids=[s.trip_id for s in request.stops],
                totals=None,
                vehicles_used=0,
                explanation=[f"Vehicle {v_req.vehicle_id} not found"],
                warnings=[]
            )
        
        driver = drivers_map.get(v_req.driver_id) if v_req.driver_id else None
        if v_req.driver_id and not driver:
            return OptimizeFleetResponse(
                status="DRIVER_UNAVAILABLE",
                routes=[],
                unassigned_trip_ids=[s.trip_id for s in request.stops],
                totals=None,
                vehicles_used=0,
                explanation=[f"Driver {v_req.driver_id} not found"],
                warnings=[]
            )
        
        # Get cost rates from config
        hub = hub_config.get(v_req.vehicle_id)
        if request.require_hub_routing and not hub:
            return OptimizeFleetResponse(
                status="MISSING_HUB_DATA",
                routes=[],
                unassigned_trip_ids=[s.trip_id for s in request.stops],
                totals=None,
                vehicles_used=0,
                explanation=[f"Vehicle {v_req.vehicle_id} has no hub configured"],
                warnings=[]
            )
        
        vehicle_inputs.append(OptimizeVehicleInput(
            vehicle_id=v_req.vehicle_id,
            capacity_kg=vehicle.capacity_kg,
            start_location=0,  # Will be updated with depot index
            avg_kmpl_rated=hub.avg_kmpl_rated if hub else vehicle.avg_kmpl_rated,
            fuel_price_per_l=hub.fuel_price_per_l if hub else vehicle.fuel_price_per_l,
        ))
    
    # Get OSRM matrices
    from app.services.route_optimizer import _fetch_matrices, _build_jobs, _build_vehicles, _add_depot_node
    durations, distances = await _fetch_matrices(request.stops)
    jobs = _build_jobs(request.stops)
    coordinates = [[s.latitude, s.longitude] for s in request.stops]
    
    # Use first stop as depot fallback
    depot_coord = [request.stops[0].latitude, request.stops[0].longitude]
    durations, distances, coordinates, depot_idx = _add_depot_node(durations, distances, coordinates, depot_coord)
    
    # Update start_location to depot index
    for v in vehicle_inputs:
        v.start_location = depot_idx
    
    # Build payload for fleet optimizer
    payload = {
        "jobs": jobs,
        "vehicles": [v.model_dump() for v in vehicle_inputs],
        "duration_matrix": durations,
        "distance_matrix": distances,
        "coordinates": coordinates,
        "driver_cost_per_hour": cost_config.get("driver_cost_per_hour", 200.0),
        "operating_cost_per_km": cost_config.get("operating_cost_per_km", 50.0),
        "iterations": 1000,
        "seed": 42,
    }
    
    # Call fleet optimizer
    try:
        result = await ml_client.optimize_fleet_routes(payload)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502, detail=f"Optimization service error: {exc.response.status_code} {exc.response.text}"
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Optimization service unavailable: {exc}")
    
    return result


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


@router.post("/lns/trigger", status_code=202)
async def trigger_lns():
    """Manually trigger an LNS optimization run."""
    job_id = create_lns_job()
    return {"message": "LNS optimization queued", "job_id": job_id}


def _serialize_lns_run(run) -> dict:
    """JSON-safe serialization of an OptimizationRun for the impact panel."""
    old_cost = run.old_cost
    improvement_pct = None
    if run.improvement is not None and old_cost:
        improvement_pct = round((run.improvement / old_cost) * 100, 2)
    return {
        "run_id": str(run.id),
        "run_type": run.optimization_type,
        "status": run.status,
        "old_cost": run.old_cost,
        "new_cost": run.new_cost,
        "improvement": run.improvement,
        "improvement_pct": improvement_pct,
        "routes_affected": run.routes_affected,
        "trips_reinserted": run.trips_reinserted,
        "execution_time_ms": run.execution_time_ms,
        "destroy_strategy": run.destroy_strategy,
        "repair_strategy": run.repair_strategy,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "routes_before": run.routes_before,
        "routes_after": run.routes_after,
    }


@router.get("/lns/history")
def lns_history(limit: int = 20, db: Session = Depends(get_db)):
    """Recent LNS optimization runs with before/after plan snapshots.

    Powers the Live Ops "LNS Impact" panel (Before ⇄ After comparison).
    """
    runs = (
        db.query(OptimizationRun)
        .filter(OptimizationRun.optimization_type.in_(["TRIGGERED_LNS", "PERIODIC_LNS"]))
        .order_by(OptimizationRun.created_at.desc())
        .limit(max(1, min(limit, 100)))
        .all()
    )
    return [_serialize_lns_run(r) for r in runs]


@router.get("/lns/history/{run_id}")
def lns_run_detail(run_id: uuid.UUID, db: Session = Depends(get_db)):
    """A single LNS run with full before/after snapshots."""
    run = db.get(OptimizationRun, run_id)
    if not run or run.optimization_type not in ("TRIGGERED_LNS", "PERIODIC_LNS"):
        raise HTTPException(status_code=404, detail="LNS run not found")
    return _serialize_lns_run(run)


@router.post("/{route_id}/reoptimize", response_model=RouteRead)
async def reoptimize_route(route_id: uuid.UUID, db: Session = Depends(get_db)):
    """Reoptimize a specific route using greedy insertion."""
    route = route_service.get_route(db, route_id)
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")

    # Run a single-route greedy reoptimization
    # This is a simplified version - in production, use LNS with route_destroy
    from app.optimization.greedy.insertion import greedy_insertion
    from app.models.trip import Trip

    # Get unassigned trips that could fit this route
    unassigned_trips = db.query(Trip).filter(
        Trip.route_id.is_(None),
        Trip.status == "scheduled",
    ).limit(10).all()

    for trip in unassigned_trips:
        result = greedy_insertion.assign_trip(db, trip)
        if result.success and result.route and result.route.route_id == route.route_id:
            greedy_insertion.apply_insertion(db, result.insertion_option, trip)

    db.refresh(route)
    return route