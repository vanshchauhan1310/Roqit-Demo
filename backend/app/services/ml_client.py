import httpx

from app.core.config import settings


async def predict_eta(payload: dict) -> dict:
    """Calls the standalone ML service over HTTP so backend and ML remain decoupled."""
    async with httpx.AsyncClient(base_url=settings.ML_SERVICE_URL, timeout=10.0) as client:
        response = await client.post("/predict/eta", json=payload)
        response.raise_for_status()
        return response.json()


async def predict_delay(payload: dict) -> dict:
    """Calls the standalone ML service's delay model. payload must contain every
    field in ml/feature_contract_v2.json's feature_order."""
    async with httpx.AsyncClient(base_url=settings.ML_SERVICE_URL, timeout=10.0) as client:
        response = await client.post("/predict/delay", json=payload)
        response.raise_for_status()
        return response.json()


async def predict_expected_delay(payload: dict) -> dict:
    """Same 25-field payload as predict_delay, but calls the regression model
    that returns expected delay in minutes instead of a probability."""
    async with httpx.AsyncClient(base_url=settings.ML_SERVICE_URL, timeout=10.0) as client:
        response = await client.post("/predict/expected-delay", json=payload)
        response.raise_for_status()
        return response.json()


async def predict_fuel_liters(payload: dict) -> dict:
    """payload must contain every field in build_features.COST_FEATURE_ORDER."""
    async with httpx.AsyncClient(base_url=settings.ML_SERVICE_URL, timeout=10.0) as client:
        response = await client.post("/predict/fuel-liters", json=payload)
        response.raise_for_status()
        return response.json()


async def predict_trip_cost(payload: dict) -> dict:
    """payload must contain every field in build_features.COST_FEATURE_ORDER."""
    async with httpx.AsyncClient(base_url=settings.ML_SERVICE_URL, timeout=10.0) as client:
        response = await client.post("/predict/trip-cost", json=payload)
        response.raise_for_status()
        return response.json()
