from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "postgresql+psycopg2://fleet:fleet@localhost:5432/fleet_db"
    ML_SERVICE_URL: str = "http://localhost:8001"
    BACKEND_CORS_ORIGINS: str = "http://localhost:5173"
    SECRET_KEY: str = "changeme"

    # Nominatim (OpenStreetMap) geocoding — free, no API key, but requires an
    # identifying User-Agent per their usage policy: https://operations.osmfoundation.org/policies/nominatim/
    NOMINATIM_URL: str = "https://nominatim.openstreetmap.org/search"
    GEOCODE_USER_AGENT: str = "FleetOptimizationPlatform/1.0"

    # OSRM (Open Source Routing Machine) — free public demo server, used for both
    # real route geometry (frontend) and the duration/distance matrix (route optimizer).
    OSRM_BASE_URL: str = "https://router.project-osrm.org"

    # OpenWeather Current Weather API — per-stop weather, cached on route_stops
    # and refreshed lazily once it's over an hour old.
    OPENWEATHER_API_KEY: str = ""
    OPENWEATHER_URL: str = "https://api.openweathermap.org/data/2.5/weather"

    # No live fuel-price feed is wired in — single configurable default used for
    # every trip's ML features (fuel_price_per_l) instead of asking per-trip.
    DEFAULT_FUEL_PRICE_PER_L: float = 92.5


settings = Settings()
