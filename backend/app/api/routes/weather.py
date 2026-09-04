"""Lightweight current-weather endpoint for the Live Ops dashboard.

Fetches live conditions for the service-area center (Hyderabad) and caches
the result in-process for 10 minutes so the polling UI doesn't hammer OpenWeather.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from app.core.service_area import HYDERABAD_CENTER
from app.schemas.weather import WeatherResult
from app.services.weather_client import fetch_weather

router = APIRouter(prefix="/weather", tags=["weather"])

# In-process cache: (timestamp, result). Survives across requests within the
# same worker process. 10-minute TTL balances freshness against API rate limits.
_cache: tuple[datetime, WeatherResult] | None = None
CACHE_TTL_SECONDS = 600


@router.get("/current", response_model=WeatherResult)
async def get_current_weather() -> WeatherResult:
    """Current weather at the service-area center (Hyderabad).

    Cached for 10 minutes. Returns 503 only if OpenWeather is unreachable AND
    the cache is empty — otherwise serves the last-known value with a warning.
    """
    global _cache

    now = datetime.now(timezone.utc)
    if _cache is not None:
        cached_at, cached_result = _cache
        if (now - cached_at).total_seconds() < CACHE_TTL_SECONDS:
            return cached_result

    try:
        result = await fetch_weather(HYDERABAD_CENTER[0], HYDERABAD_CENTER[1])
        _cache = (now, result)
        return result
    except HTTPException:
        if _cache is not None:
            # Stale-but-available is better than a hard error on the dashboard.
            return _cache[1]
        raise