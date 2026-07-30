from fastapi import APIRouter

from app.schemas.geocode import GeocodeRequest, GeocodeResult
from app.services.geocode_client import geocode_address

router = APIRouter(prefix="/geocode", tags=["geocode"])


@router.post("", response_model=GeocodeResult)
async def geocode(request: GeocodeRequest):
    return await geocode_address(request.address)
