import httpx
from fastapi import HTTPException

from app.core.config import settings
from app.schemas.geocode import GeocodeResult


async def geocode_address(address: str) -> GeocodeResult:
    """Forward-geocodes a free-text address via Nominatim (OpenStreetMap).

    Free, no API key — but Nominatim's usage policy requires an identifying
    User-Agent and caps usage at ~1 request/second.
    """
    params = {"q": address, "format": "json", "limit": 1}
    headers = {"User-Agent": settings.GEOCODE_USER_AGENT}

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(settings.NOMINATIM_URL, params=params, headers=headers)

    if response.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Geocoding provider returned {response.status_code}")

    results = response.json()
    if not results:
        raise HTTPException(status_code=404, detail="Address not found")

    match = results[0]
    return GeocodeResult(lat=float(match["lat"]), lng=float(match["lon"]), error_radius=None)
