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
    """Calls the standalone ML service's expected-delay (minutes) model. Same
    25-field payload shape as predict_delay."""
    async with httpx.AsyncClient(base_url=settings.ML_SERVICE_URL, timeout=10.0) as client:
        response = await client.post("/predict/expected-delay", json=payload)
        response.raise_for_status()
        return response.json()


async def predict_fuel_liters(payload: dict) -> dict:
    """Calls the standalone ML service's fuel-consumption model. payload must
    contain every field in ml/src/features/build_features.py::COST_FEATURE_ORDER."""
    async with httpx.AsyncClient(base_url=settings.ML_SERVICE_URL, timeout=10.0) as client:
        response = await client.post("/predict/fuel-liters", json=payload)
        response.raise_for_status()
        return response.json()


async def predict_trip_cost(payload: dict) -> dict:
    """Calls the standalone ML service's trip-cost model. Same 10-field payload
    shape as predict_fuel_liters."""
    async with httpx.AsyncClient(base_url=settings.ML_SERVICE_URL, timeout=10.0) as client:
        response = await client.post("/predict/trip-cost", json=payload)
        response.raise_for_status()
        return response.json()
