from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.driver_intelligence import DriverIntelligenceRead
from app.schemas.eta_prediction import EtaPredictionRead
from app.schemas.fuel_cost import FuelCostEstimateRead, TripCostPredictionRead
from app.schemas.trip import TripCreate, TripFilterOptions, TripOutcomeUpdate, TripRead, TripUpdateStatus
from app.schemas.vehicle_intelligence import VehicleIntelligenceRead
from app.services import (
    driver_intelligence_service,
    eta_service,
    fuel_cost_service,
    trip_service,
    vehicle_intelligence_service,
)

router = APIRouter(prefix="/trips", tags=["trips"])


@router.post("", response_model=TripRead, status_code=201)
async def create_trip(trip_in: TripCreate, db: Session = Depends(get_db)):
    try:
        return await trip_service.create_trip(db, trip_in)
    except trip_service.DuplicateIdError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except trip_service.LoadExceedsCapacityError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("", response_model=list[TripRead])
def list_trips(
    skip: int = 0,
    limit: int = 100,
    search: str | None = None,
    status: str | None = None,
    driver: str | None = None,
    pickup_date: date | None = None,
    unassigned: bool = Query(False, description="Return only trips not assigned to any route"),
    db: Session = Depends(get_db),
):
    if unassigned:
        return trip_service.list_unassigned_trips(db)
    return trip_service.list_trips(db, skip, limit, search, status, driver, pickup_date)


@router.get("/filter-options", response_model=TripFilterOptions)
def get_filter_options(db: Session = Depends(get_db)):
    return trip_service.get_filter_options(db)


@router.get("/{trip_id}", response_model=TripRead)
def get_trip(trip_id: str, db: Session = Depends(get_db)):
    trip = trip_service.get_trip(db, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    return trip


@router.patch("/{trip_id}/status", response_model=TripRead)
def update_trip_status(trip_id: str, status_in: TripUpdateStatus, db: Session = Depends(get_db)):
    trip = trip_service.get_trip(db, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    return trip_service.update_trip_status(db, trip, status_in.status)


@router.get("/{trip_id}/eta-prediction", response_model=EtaPredictionRead)
async def get_eta_prediction(trip_id: str, db: Session = Depends(get_db)):
    """Rule-based weather-adjusted ETA (OSRM + hand-coded weather multiplier),
    distinct from the ML-based /api/predictions/expected-delay."""
    trip = trip_service.get_trip(db, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    result = await eta_service.predict_eta_for_trip(trip)
    return EtaPredictionRead(**result)


@router.get("/{trip_id}/fuel-cost-estimate", response_model=FuelCostEstimateRead)
async def get_fuel_cost_estimate(trip_id: str, db: Session = Depends(get_db)):
    trip = trip_service.get_trip(db, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    result = await fuel_cost_service.get_fuel_cost_estimate(trip)
    return FuelCostEstimateRead(**result)


@router.get("/{trip_id}/cost-prediction", response_model=TripCostPredictionRead)
async def get_cost_prediction(trip_id: str, db: Session = Depends(get_db)):
    trip = trip_service.get_trip(db, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    try:
        result = await fuel_cost_service.predict_trip_cost_for_trip(trip)
    except (
        fuel_cost_service.MissingFeatureDataError,
        fuel_cost_service.UnsupportedCategoryError,
        fuel_cost_service.InvalidFeatureRangeError,
    ) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return TripCostPredictionRead(**result)


@router.get("/{trip_id}/vehicle-intelligence", response_model=VehicleIntelligenceRead)
async def get_vehicle_intelligence(trip_id: str, db: Session = Depends(get_db)):
    trip = trip_service.get_trip(db, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    result = await vehicle_intelligence_service.get_vehicle_intelligence(db, trip)
    if result is None:
        raise HTTPException(status_code=422, detail=f"Trip {trip_id} has no assigned vehicle")
    return result


@router.get("/{trip_id}/driver-intelligence", response_model=DriverIntelligenceRead)
async def get_driver_intelligence(trip_id: str, db: Session = Depends(get_db)):
    trip = trip_service.get_trip(db, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    result = driver_intelligence_service.get_driver_intelligence(db, trip)
    if result is None:
        raise HTTPException(status_code=422, detail=f"Trip {trip_id} has no assigned driver")
    return result


@router.patch("/{trip_id}/outcome", response_model=TripRead)
def complete_trip(trip_id: str, outcome_in: TripOutcomeUpdate, db: Session = Depends(get_db)):
    """Records the real delay outcome once a trip finishes, feeding future
    driver/vehicle/route history features used by /predictions/delay."""
    trip = trip_service.get_trip(db, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    return trip_service.complete_trip(db, trip, outcome_in)
