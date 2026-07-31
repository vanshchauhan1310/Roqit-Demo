from pydantic import BaseModel


class WeatherResult(BaseModel):
    condition: str  # OpenWeather's "main" bucket, e.g. Clear/Clouds/Rain/Thunderstorm/Snow/Fog
    description: str | None = None
    temp_c: float | None = None
