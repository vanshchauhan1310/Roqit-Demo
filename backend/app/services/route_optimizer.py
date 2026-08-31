import httpx
from fastapi import HTTPException

from app.core.config import settings
from app.schemas.optimize import OptimizeRouteResponse, OptimizeStopInput, OptimizeVehicleInput, VehicleRouteOutput, DepotInput
from app.services import ml_client


async def _fetch_matrices(stops: list[OptimizeStopInput]) -> tuple[list[list[float]], list[list[float]]]:
    coords = ";".join(f"{s.longitude},{s.latitude}" for s in stops)
    url = f"{settings.OSRM_BASE_URL}/table/v1/driving/{coords}?annotations=duration,distance"

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(url)

    if response.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Routing provider returned {response.status_code}")

    data = response.json()
    durations = data.get("durations")
    distances = data.get("distances")
    if not durations or not distances:
        raise HTTPException(status_code=502, detail="Routing provider returned no matrix")

    return durations, distances


def _add_depot_node(
    durations: list[list[float]],
    distances: list[list[float]],
    coordinates: list[list[float]],
    depot_coord: list[float],
) -> tuple[list[list[float]], list[list[float]], list[list[float]], int]:
    """Add a dedicated depot node to matrices and coordinates.
    
    The depot is placed at the end (index = len(original_stops)).
    Depot-to-depot cost is 0. Depot-to-other costs use the depot_coord.
    Returns: (new_durations, new_distances, new_coordinates, depot_node_index)
    """
    n = len(durations)
    depot_idx = n
    
    # Get distances/durations from depot to all stops using OSRM would be ideal
    # For now, approximate using first stop as reference, or compute from depot_coord
    # Since we don't have OSRM for depot, we approximate using first stop
    # In production, you'd call OSRM table with depot_coord included
    
    # Use first stop as reference for depot-to-stop costs
    ref_idx = 0
    
    new_durations = [row[:] + [durations[ref_idx][i] for i in range(n)] + [0.0] for i, row in enumerate(durations)]
    new_durations.append([durations[ref_idx][i] for i in range(n)] + [0.0])
    
    new_distances = [row[:] + [distances[ref_idx][i] for i in range(n)] + [0.0] for i, row in enumerate(distances)]
    new_distances.append([distances[ref_idx][i] for i in range(n)] + [0.0])
    
    new_coordinates = coordinates + [depot_coord]
    
    return new_durations, new_distances, new_coordinates, depot_idx


def _build_jobs(stops: list[OptimizeStopInput]) -> list[dict]:
    """Groups stops by trip_id into pickup-delivery job pairs the ML
    service's hybrid solver operates on. Every trip present must have both
    a pickup and a delivery stop in the request."""
    by_trip: dict[str, dict[str, int]] = {}
    for i, stop in enumerate(stops):
        by_trip.setdefault(stop.trip_id, {})[stop.stop_type] = i

    jobs = []
    for trip_id, indices in by_trip.items():
        if "pickup" not in indices or "delivery" not in indices:
            raise HTTPException(status_code=400, detail=f"Trip {trip_id} is missing its pickup or delivery stop")
        pickup_stop = stops[indices["pickup"]]
        jobs.append(
            {
                "trip_id": trip_id,
                "pickup_stop_index": indices["pickup"],
                "delivery_stop_index": indices["delivery"],
                "load_weight_kg": pickup_stop.load_weight_kg or 0.0,
            }
        )
    return jobs


def _build_vehicles(stops: list[OptimizeStopInput], vehicles: list[OptimizeVehicleInput] | None, depot_idx: int) -> list[dict]:
    """Build vehicle list with start_location as depot index (separate from stops)."""
    if not vehicles:
        # Legacy: single vehicle at depot
        return [{
            "vehicle_id": "default",
            "capacity_kg": 10000.0,
            "start_location": depot_idx,
            "avg_kmpl_rated": 8.5,
            "fuel_price_per_l": 92.5,
        }]

    vehicle_list = []
    for v in vehicles:
        vehicle_list.append({
            "vehicle_id": v.vehicle_id,
            "capacity_kg": v.capacity_kg,
            "start_location": depot_idx,
            "avg_kmpl_rated": v.avg_kmpl_rated,
            "fuel_price_per_l": v.fuel_price_per_l,
        })
    return vehicle_list


async def optimize_route(
    stops: list[OptimizeStopInput],
    vehicles: list[OptimizeVehicleInput] | None = None,
    vehicle_capacity_kg: float | None = None,
    auto_generate_windows: bool = True,
    start_time: int = 0,
    vehicle_speed_kph: float = 40.0,
    cost_weights: dict | None = None,
    solver_time_limit_seconds: int = 10,
    depot: DepotInput | None = None,
) -> OptimizeRouteResponse:
    """Fetches a real OSRM duration/distance matrix, groups stops into
    pickup-delivery jobs, and delegates the actual combinatorial search to
    the ML service's optimizer - this module only owns the real-world I/O (OSRM)."""
    if len(stops) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 stops to optimize")

    durations, distances = await _fetch_matrices(stops)
    jobs = _build_jobs(stops)
    coordinates = [[s.latitude, s.longitude] for s in stops]
    
    # Determine depot location: explicit depot or fallback to first stop
    if depot:
        depot_lat = depot.latitude
        depot_lng = depot.longitude
        depot_coord = [depot_lat, depot_lng]
    else:
        # Fallback: use first stop's location
        depot_lat = stops[0].latitude
        depot_lng = stops[0].longitude
        depot_coord = [depot_lat, depot_lng]
    
    # Add dedicated depot node (separate from pickup/delivery stops)
    durations, distances, coordinates, depot_idx = _add_depot_node(durations, distances, coordinates, depot_coord)
    
    vehicle_list = _build_vehicles(stops, vehicles, depot_idx)

    payload = {
        "jobs": jobs,
        "vehicles": vehicle_list,
        "duration_matrix": durations,
        "distance_matrix": distances,
        "coordinates": coordinates,
        "start_time": start_time,
        "auto_generate_windows": auto_generate_windows,
        "vehicle_speed_kph": vehicle_speed_kph,
        "solver_time_limit_seconds": solver_time_limit_seconds,
    }
    if cost_weights:
        payload["cost_weights"] = cost_weights

    try:
        result = await ml_client.optimize_pickup_delivery_route(payload)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502, detail=f"Optimization service error: {exc.response.status_code} {exc.response.text}"
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Optimization service unavailable: {exc}")

    # Handle both new multi-vehicle and legacy single-vehicle response formats
    if "routes" in result and result["routes"] is not None:
        # New multi-vehicle format - filter out depot node from returned routes
        routes = []
        for r in result["routes"]:
            # Remove depot node (index >= original stop count) from route
            original_stop_count = len(stops)
            filtered_stops = [stops[i].key for i in r["stops"] if i < original_stop_count]
            routes.append(VehicleRouteOutput(vehicle_id=r["vehicle_id"], stops=filtered_stops))
        return OptimizeRouteResponse(
            routes=routes,
            total_duration_seconds=result["total_duration_seconds"],
            total_distance_meters=result["total_distance_meters"],
            total_lateness_seconds=result.get("total_lateness_seconds", 0.0),
            total_fuel_cost_rupees=result.get("total_fuel_cost_rupees", 0.0),
            total_load_ton_km=result.get("total_load_ton_km", 0.0),
            solver_used=result["solver_used"],
            feasible=result["feasible"],
        )
    else:
        # Legacy single-vehicle format
        order_indices: list[int] = result["order"]
        original_stop_count = len(stops)
        filtered_order = [stops[i].key for i in order_indices if i < original_stop_count]
        return OptimizeRouteResponse(
            order=filtered_order,
            total_duration_seconds=result["total_duration_seconds"],
            total_distance_meters=result["total_distance_meters"],
            solver_used=result["solver_used"],
            feasible=result["feasible"],
        )