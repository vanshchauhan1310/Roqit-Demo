"""One-off backfill: recomputes planned_distance_km (via OSRM) for any trip
that has real GPS coordinates but a null planned_distance_km. Trips could end
up in this state because Create Trip used to let a trip be saved before its
road-route distance had resolved (fixed in CreateTripModal.tsx - the button
now blocks on it), so nothing ever wrote this field for them. Every ML
prediction that needs planned_distance_km (delay, expected-delay, fuel-cost)
fails for a trip stuck like this.

Usage: run from backend/, with its venv active:
    python backfill_planned_distance_km.py
"""

import asyncio

import httpx
from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.trip import Trip


async def _fetch_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float | None:
    url = f"{settings.OSRM_BASE_URL}/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=false"
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(url)
    if response.status_code != 200:
        return None
    routes = response.json().get("routes")
    if not routes:
        return None
    return routes[0]["distance"] / 1000


async def main() -> None:
    db = SessionLocal()
    try:
        trips = list(
            db.execute(
                select(Trip).where(
                    Trip.planned_distance_km.is_(None),
                    Trip.gps_start_lat.is_not(None),
                    Trip.gps_start_lon.is_not(None),
                    Trip.gps_end_lat.is_not(None),
                    Trip.gps_end_lon.is_not(None),
                )
            ).scalars()
        )
        print(f"Found {len(trips)} trip(s) with real coordinates but no planned_distance_km.")

        fixed, failed = 0, 0
        for trip in trips:
            distance_km = await _fetch_distance_km(
                trip.gps_start_lat, trip.gps_start_lon, trip.gps_end_lat, trip.gps_end_lon
            )
            if distance_km is None:
                print(f"  {trip.trip_id}: OSRM lookup failed, skipped")
                failed += 1
                continue
            trip.planned_distance_km = round(distance_km, 1)
            db.add(trip)
            print(f"  {trip.trip_id}: planned_distance_km = {trip.planned_distance_km} km")
            fixed += 1

        db.commit()
        print(f"Done. Fixed {fixed}, failed {failed}.")
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
