import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.route import Route, RouteStop
from app.schemas.route import RouteCreate, RouteStopCreate


def create_route(db: Session, route_in: RouteCreate) -> Route:
    route = Route(trip_id=route_in.trip_id, name=route_in.name)
    db.add(route)
    db.flush()

    for position, stop_in in enumerate(route_in.stops, start=1):
        stop_data = stop_in.model_dump()
        if stop_data.get("sequence") is None:
            stop_data["sequence"] = position
        db.add(RouteStop(route_id=route.route_id, **stop_data))

    db.commit()
    db.refresh(route)
    return route


def get_route(db: Session, route_id: uuid.UUID) -> Route | None:
    return db.get(Route, route_id)


def list_routes(db: Session, skip: int = 0, limit: int = 100, trip_id: str | None = None) -> list[Route]:
    query = db.query(Route)
    if trip_id:
        query = query.filter(Route.trip_id == trip_id)
    return query.order_by(Route.created_at.desc()).offset(skip).limit(limit).all()


def update_route_status(db: Session, route: Route, status: str) -> Route:
    route.status = status
    db.add(route)
    db.commit()
    db.refresh(route)
    return route


def assign_trip(db: Session, route: Route, trip_id: str) -> Route:
    route.trip_id = trip_id
    db.add(route)
    db.commit()
    db.refresh(route)
    return route


def add_stop_to_route(db: Session, route: Route, stop_in: RouteStopCreate) -> RouteStop:
    stop_data = stop_in.model_dump()

    if stop_data.get("sequence") is None:
        max_sequence = db.query(func.max(RouteStop.sequence)).filter(RouteStop.route_id == route.route_id).scalar()
        stop_data["sequence"] = (max_sequence or 0) + 1

    stop = RouteStop(route_id=route.route_id, **stop_data)
    db.add(stop)
    db.commit()
    db.refresh(stop)
    return stop
