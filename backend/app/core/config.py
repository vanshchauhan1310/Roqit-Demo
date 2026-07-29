from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "postgresql+psycopg2://fleet:fleet@localhost:5432/fleet_db"
    ML_SERVICE_URL: str = "http://localhost:8001"
    BACKEND_CORS_ORIGINS: str = "http://localhost:5173"
    SECRET_KEY: str = "changeme"


settings = Settings()
