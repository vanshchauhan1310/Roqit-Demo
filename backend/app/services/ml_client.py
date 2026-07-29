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
