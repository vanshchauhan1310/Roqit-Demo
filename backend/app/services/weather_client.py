import httpx
from fastapi import HTTPException

from app.core.config import settings


async def get_current_weather(lat: float, lon: float) -> dict:
    """Fetches live current weather for a coordinate from OpenWeather's
    Current Weather Data API. Requires OPENWEATHER_API_KEY in .env - see
    https://openweathermap.org/api."""
    if not settings.OPENWEATHER_API_KEY:
        raise HTTPException(status_code=500, detail="OPENWEATHER_API_KEY is not configured")

    params = {"lat": lat, "lon": lon, "appid": settings.OPENWEATHER_API_KEY, "units": "metric"}

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(settings.OPENWEATHER_BASE_URL, params=params)

    if response.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Weather provider returned {response.status_code}")

    return response.json()
