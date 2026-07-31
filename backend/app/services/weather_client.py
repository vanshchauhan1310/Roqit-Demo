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

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(settings.OPENWEATHER_BASE_URL, params=params)
    except httpx.HTTPError as exc:
        # Network-level failure (timeout, DNS, connection refused) - not an
        # HTTP status, so it wouldn't otherwise be caught by callers that
        # only handle HTTPException from a bad response.
        raise HTTPException(status_code=502, detail=f"Weather provider unreachable: {exc}") from exc

    if response.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Weather provider returned {response.status_code}")

    return response.json()


def map_condition_to_ml_vocabulary(weather: dict) -> str:
    """Collapses OpenWeather's ~30 raw conditions onto the 5-category
    vocabulary the trained models were built on (feature_contract_v2.json:
    Clear, Extreme Heat, Fog, Rain, Storm). Necessarily approximate - there's
    no dedicated "Snow" or "Clouds" category in training data, so this picks
    the closest match rather than inventing a new one the models were never
    trained on (would trip UnsupportedCategoryError)."""
    temp_c = weather.get("main", {}).get("temp")
    if temp_c is not None and temp_c >= 40:
        return "Extreme Heat"

    condition = weather["weather"][0]["main"]
    if condition in ("Thunderstorm", "Squall", "Tornado", "Snow"):
        return "Storm"
    if condition in ("Rain", "Drizzle"):
        return "Rain"
    if condition in ("Fog", "Mist", "Haze", "Smoke", "Dust", "Sand", "Ash"):
        return "Fog"
    return "Clear"  # Clear, Clouds, and anything else neutral


async def get_ml_weather_condition(lat: float | None, lon: float | None) -> str | None:
    """Best-effort live weather, mapped to the ML models' trained vocabulary.
    Returns None (never raises) if coordinates are missing or the provider
    call fails - callers should fall back to a stored value in that case."""
    if lat is None or lon is None:
        return None
    try:
        weather = await get_current_weather(lat, lon)
    except HTTPException:
        return None
    return map_condition_to_ml_vocabulary(weather)
