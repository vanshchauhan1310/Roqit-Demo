import httpx
from fastapi import HTTPException

from app.core.config import settings
from app.schemas.optimize import OptimizeRouteResponse, OptimizeStopInput
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


async def optimize_route(stops: list[OptimizeStopInput], vehicle_capacity_kg: float | None = None) -> OptimizeRouteResponse:
    """Fetches a real OSRM duration/distance matrix, groups stops into
    pickup-delivery jobs, and delegates the actual combinatorial search to
    the ML service's hybrid pickup-delivery optimizer (see
    ml/src/optimizer/) - this module only owns the real-world I/O (OSRM),
    matching the rest of this app's backend-never-does-ML-itself convention."""
    if len(stops) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 stops to optimize")

    durations, distances = await _fetch_matrices(stops)
    jobs = _build_jobs(stops)
    coordinates = [[s.latitude, s.longitude] for s in stops]

    try:
        result = await ml_client.optimize_pickup_delivery_route(
            {
                "jobs": jobs,
                "duration_matrix": durations,
                "distance_matrix": distances,
                "coordinates": coordinates,
                "vehicle_capacity_kg": vehicle_capacity_kg,
            }
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502, detail=f"Optimization service error: {exc.response.status_code} {exc.response.text}"
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Optimization service unavailable: {exc}")

    order_indices: list[int] = result["order"]
    return OptimizeRouteResponse(
        order=[stops[i].key for i in order_indices],
        total_duration_seconds=result["total_duration_seconds"],
        total_distance_meters=result["total_distance_meters"],
        solver_used=result["solver_used"],
    )
