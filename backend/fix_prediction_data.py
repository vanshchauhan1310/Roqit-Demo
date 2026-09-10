"""One-off data repair so the ML prediction pipeline can run on seeded trips.

Fixes every blocking gap found in the prediction failure analysis (see
docs/PREDICTION_MODEL_DECK.md):

1. vehicle_master.fuel_type: "diesel" -> "Diesel" (ML contract Literal), NULL -> "Diesel"
2. driver_master.base_location: NULL -> "Hyderabad" (the fleet's real base)
3. trips.planned_distance_km: NULL -> OSRM road-route distance (same as
   backfill_planned_distance_km.py)
4. trips.pickup_time: NULL -> now (demo data has no booking timestamp)
5. trips.planned_delivery_time: NULL -> pickup_time + distance/40 kmph
6. trips.weather_condition: NULL -> "Clear" (no OPENWEATHER_API_KEY configured,
   so the live-lookup fallback can never resolve either)

Usage (Docker):   docker compose exec backend python fix_prediction_data.py
Usage (local):    cd backend && python fix_prediction_data.py
Idempotent:       only touches rows whose fields are still NULL/wrong-case.
"""
import asyncio
from datetime import datetime, timedelta

import httpx
from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.trip import Trip
from app.services.trip_service import DEMO_ACTUAL_DISTANCE_FACTOR

AVG_SPEED_KMPH = 40.0  # conservative planning speed for the demo fleet


async def _fetch_distance_km(lat1, lon1, lat2, lon2) -> float | None:
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
        # --- 1. vehicle fuel_type casing + NULLs ---
        from app.models.vehicle import Vehicle
        fixed = 0
        for v in db.execute(select(Vehicle)).scalars():
            new_fuel = None
            if v.fuel_type is None:
                new_fuel = "Diesel"
            elif v.fuel_type.lower() == "diesel" and v.fuel_type != "Diesel":
                new_fuel = "Diesel"
            elif v.fuel_type.lower() == "cng" and v.fuel_type != "CNG":
                new_fuel = "CNG"
            if new_fuel:
                print(f"  vehicle {v.vehicle_id}: fuel_type {v.fuel_type!r} -> {new_fuel!r}")
                v.fuel_type = new_fuel
                db.add(v)
                fixed += 1
        print(f"[1] fuel_type fixed on {fixed} vehicle(s)")

        # --- 2. driver base_location + experience_years NULLs ---
        from app.models.driver import Driver
        fixed = fixed_exp = 0
        for d in db.execute(select(Driver)).scalars():
            if d.base_location is None:
                print(f"  driver {d.driver_id}: base_location NULL -> 'Hyderabad'")
                d.base_location = "Hyderabad"
                db.add(d)
                fixed += 1
            if d.experience_years is None:
                print(f"  driver {d.driver_id}: experience_years NULL -> 5.0")
                d.experience_years = 5.0
                db.add(d)
                fixed_exp += 1
        print(f"[2] base_location fixed on {fixed} driver(s), "
              f"experience_years on {fixed_exp} driver(s)")

        # --- 3. planned_distance_km via OSRM ---
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
        print(f"[3] {len(trips)} trip(s) missing planned_distance_km")
        ok = failed = 0
        for trip in trips:
            distance_km = await _fetch_distance_km(
                trip.gps_start_lat, trip.gps_start_lon, trip.gps_end_lat, trip.gps_end_lon
            )
            if distance_km is None:
                failed += 1
                # Release the txn so Postgres' idle-in-transaction timeout
                # can't kill the connection on slow OSRM responses.
                db.commit()
                continue
            trip.planned_distance_km = round(distance_km, 1)
            if trip.actual_distance_km is None:
                trip.actual_distance_km = round(distance_km * DEMO_ACTUAL_DISTANCE_FACTOR, 1)
            db.add(trip)
            db.commit()
            ok += 1
        print(f"[3] planned_distance_km backfilled on {ok} trip(s), {failed} OSRM failure(s)")

        # --- 4-6. pickup_time / planned_delivery_time / weather_condition ---
        now = datetime.now()
        fixed_t = fixed_w = 0
        for trip in db.execute(select(Trip)).scalars():
            if trip.pickup_time is None:
                trip.pickup_time = now
            if trip.planned_delivery_time is None:
                if trip.planned_distance_km:
                    hours = trip.planned_distance_km / AVG_SPEED_KMPH
                else:
                    hours = 4.0
                trip.planned_delivery_time = trip.pickup_time + timedelta(hours=hours)
                fixed_t += 1
            if trip.weather_condition is None:
                trip.weather_condition = "Clear"
                fixed_w += 1
            db.add(trip)
        db.commit()
        print(f"[4-6] times fixed on {fixed_t} trip(s), weather on {fixed_w} trip(s)")
        print("Done.")
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
