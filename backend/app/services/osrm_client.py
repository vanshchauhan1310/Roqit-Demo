import httpx

from app.core.config import settings


async def get_route_duration_hours(start_lat: float, start_lon: float, end_lat: float, end_lon: float) -> float | None:
    """Real road-network duration between two points via OSRM (no traffic/weather -
    those are applied on top by eta_service). Returns None if OSRM is unreachable
    or the coordinates can't be routed, so callers can fall back to a simpler estimate."""
    coords = f"{start_lon},{start_lat};{end_lon},{end_lat}"
    url = f"{settings.OSRM_BASE_URL}/route/v1/driving/{coords}?overview=false"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
        if response.status_code != 200:
            return None
        data = response.json()
        route = (data.get("routes") or [None])[0]
        if not route:
            return None
        return route["duration"] / 3600
    except Exception:
        return None
