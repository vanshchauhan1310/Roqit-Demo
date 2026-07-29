import uuid

from sqlalchemy.orm import Session

from app.models.route import Route, RouteStop
from app.schemas.route import RouteCreate


def create_route(db: Session, route_in: RouteCreate) -> Route:
    stops_in = route_in.stops
    route = Route(trip_id=route_in.trip_id, name=route_in.name)
    db.add(route)
    db.flush()

    for stop_in in stops_in:
        db.add(RouteStop(route_id=route.route_id, **stop_in.model_dump()))

    db.commit()
    db.refresh(route)
    return route


def get_route(db: Session, route_id: uuid.UUID) -> Route | None:
    return db.get(Route, route_id)


def list_routes(db: Session, skip: int = 0, limit: int = 100) -> list[Route]:
    return db.query(Route).order_by(Route.created_at.desc()).offset(skip).limit(limit).all()


def update_route_status(db: Session, route: Route, status: str) -> Route:
    route.status = status
    db.add(route)
    db.commit()
    db.refresh(route)
    return route
