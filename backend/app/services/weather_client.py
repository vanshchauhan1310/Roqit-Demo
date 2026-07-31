import httpx
from fastapi import HTTPException

from app.core.config import settings
from app.schemas.weather import WeatherResult


async def fetch_weather(lat: float, lon: float) -> WeatherResult:
    """Fetches current weather for a coordinate via OpenWeather's Current Weather API."""
    if not settings.OPENWEATHER_API_KEY:
        raise HTTPException(status_code=503, detail="Weather is not configured (OPENWEATHER_API_KEY missing).")

    params = {"lat": lat, "lon": lon, "appid": settings.OPENWEATHER_API_KEY, "units": "metric"}

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(settings.OPENWEATHER_URL, params=params)

    if response.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Weather provider returned {response.status_code}")

    data = response.json()
    weather = (data.get("weather") or [{}])[0]

    return WeatherResult(
        condition=weather.get("main", "Unknown"),
        description=weather.get("description"),
        temp_c=(data.get("main") or {}).get("temp"),
    )


# The delay/expected-delay models were trained on this 5-value vocabulary, which
# doesn't line up 1:1 with OpenWeather's "main" categories — this is a best-effort
# mapping, not a precise translation (mirrors the same table in the frontend wizard,
# where the derived value is still shown to the dispatcher as an editable default).
_ML_WEATHER_VOCABULARY = {
    "Clear": "Clear",
    "Clouds": "Clear",
    "Rain": "Rain",
    "Drizzle": "Rain",
    "Thunderstorm": "Storm",
    "Snow": "Storm",
    "Mist": "Fog",
    "Fog": "Fog",
    "Haze": "Fog",
}


def map_condition_to_ml_vocabulary(condition: str) -> str:
    return _ML_WEATHER_VOCABULARY.get(condition, "Clear")


async def get_ml_weather_condition(lat: float | None, lon: float | None) -> str | None:
    """Live weather, mapped to the ML vocabulary. Returns None (never raises) if
    coordinates are missing or the provider call fails, so callers can fall back
    to a stored value instead of hard-failing the whole prediction."""
    if lat is None or lon is None:
        return None
    try:
        result = await fetch_weather(lat, lon)
    except Exception:
        return None
    return map_condition_to_ml_vocabulary(result.condition)
