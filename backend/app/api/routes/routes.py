import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.route import RouteCreate, RouteRead, RouteUpdateStatus
from app.services import route_service

router = APIRouter(prefix="/routes", tags=["routes"])


@router.post("", response_model=RouteRead, status_code=201)
def create_route(route_in: RouteCreate, db: Session = Depends(get_db)):
    return route_service.create_route(db, route_in)


@router.get("", response_model=list[RouteRead])
def list_routes(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return route_service.list_routes(db, skip, limit)


@router.get("/{route_id}", response_model=RouteRead)
def get_route(route_id: uuid.UUID, db: Session = Depends(get_db)):
    route = route_service.get_route(db, route_id)
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")
    return route


@router.patch("/{route_id}/status", response_model=RouteRead)
def update_route_status(route_id: uuid.UUID, status_in: RouteUpdateStatus, db: Session = Depends(get_db)):
    route = route_service.get_route(db, route_id)
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")
    return route_service.update_route_status(db, route, status_in.status)
