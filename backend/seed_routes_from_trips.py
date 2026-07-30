"""Seed routes/route_stops from existing trips (origin -> destination as two stops).

Only creates data in routes/route_stops — never touches trips. Safe to re-run;
trips that already have a route are skipped.

Usage (from backend/, with the venv active):
    python seed_routes_from_trips.py             # seed all trips
    python seed_routes_from_trips.py --limit 20  # seed only the first 20
"""
import argparse

from app.db.session import SessionLocal
from app.models.route import Route, RouteStop
from app.models.trip import Trip


def seed(limit: int | None = None) -> None:
    db = SessionLocal()
    try:
        already_seeded = {
            trip_id for (trip_id,) in db.query(Route.trip_id).filter(Route.trip_id.isnot(None))
        }

        query = db.query(Trip)
        if limit:
            query = query.limit(limit)

        created = 0
        skipped_existing = 0
        skipped_missing_fields = 0

        for trip in query:
            if trip.trip_id in already_seeded:
                skipped_existing += 1
                continue
            if not trip.origin or not trip.destination:
                skipped_missing_fields += 1
                continue

            route = Route(
                trip_id=trip.trip_id,
                name=f"{trip.origin} -> {trip.destination}",
                status="planned",
            )
            db.add(route)
            db.flush()  # populates route.route_id for the stops below

            db.add(
                RouteStop(
                    route_id=route.route_id,
                    sequence=1,
                    address=trip.origin,
                    stop_type="pickup",
                    eta=trip.pickup_time,
                    window_start=trip.pickup_time,
                )
            )
            db.add(
                RouteStop(
                    route_id=route.route_id,
                    sequence=2,
                    address=trip.destination,
                    stop_type="delivery",
                    eta=trip.planned_delivery_time,
                    window_end=trip.planned_delivery_time,
                )
            )
            created += 1

        db.commit()
        print(
            f"Created {created} routes (2 stops each). "
            f"Skipped {skipped_existing} already-seeded, {skipped_missing_fields} missing origin/destination."
        )
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="Only seed the first N trips")
    args = parser.parse_args()
    seed(args.limit)
