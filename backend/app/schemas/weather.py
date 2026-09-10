from pydantic import BaseModel


class WeatherResult(BaseModel):
    condition: str  # OpenWeather's "main" bucket, e.g. Clear/Clouds/Rain/Thunderstorm/Snow/Fog
    description: str | None = None
    temp_c: float | None = None
    feels_like_c: float | None = None
    humidity: int | None = None
    wind_speed_ms: float | None = None
    icon: str | None = None  # OpenWeather icon code (e.g. "01d")
    location_name: str | None = None
