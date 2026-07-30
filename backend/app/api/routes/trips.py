from datetime import date

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.fuel_cost import FuelCostEstimate
from app.schemas.ml_eta import MlEtaEstimate
from app.schemas.trip import TripCreate, TripFilterOptions, TripOutcomeUpdate, TripRead, TripUpdateStatus
from app.schemas.trip_cost import TripCostEstimate
from app.services import delay_prediction_service, fuel_cost_service, ml_eta_service, trip_service

router = APIRouter(prefix="/trips", tags=["trips"])


@router.post("", response_model=TripRead, status_code=201)
def create_trip(trip_in: TripCreate, db: Session = Depends(get_db)):
    try:
        return trip_service.create_trip(db, trip_in)
    except trip_service.DuplicateIdError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("", response_model=list[TripRead])
def list_trips(
    skip: int = 0,
    limit: int = 100,
    search: str | None = None,
    status: str | None = None,
    driver: str | None = None,
    pickup_date: date | None = None,
    db: Session = Depends(get_db),
):
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


@router.patch("/{trip_id}/outcome", response_model=TripRead)
def complete_trip(trip_id: str, outcome_in: TripOutcomeUpdate, db: Session = Depends(get_db)):
    """Records the real delay outcome once a trip finishes, feeding future
    driver/vehicle/route history features used by /predictions/delay."""
    trip = trip_service.get_trip(db, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    return trip_service.complete_trip(db, trip, outcome_in)


@router.get("/{trip_id}/fuel-cost-estimate", response_model=FuelCostEstimate)
async def get_fuel_cost_estimate(trip_id: str, db: Session = Depends(get_db)):
    """Low/normal/high fuel cost scenarios, derived from historical
    fuel_price_per_l quantiles (10th/50th/90th percentile) times the trip's
    estimated liters. Also classifies the trip's own current fuel_price_per_l
    into one of those three bands, if set."""
    trip = trip_service.get_trip(db, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    if trip.vehicle is None:
        raise HTTPException(status_code=404, detail="Trip has no assigned vehicle")

    try:
        return await fuel_cost_service.estimate_fuel_cost_range(db, trip, trip.vehicle)
    except (fuel_cost_service.InsufficientHistoryError, fuel_cost_service.MissingFuelInputError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/{trip_id}/cost-prediction", response_model=TripCostEstimate)
async def get_cost_prediction(trip_id: str, db: Session = Depends(get_db)):
    """Total trip cost predicted by trip_cost_xgboost_v1.pkl - a single ML
    number, distinct from the fuel-cost-estimate's historical price range."""
    trip = trip_service.get_trip(db, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    if trip.vehicle is None:
        raise HTTPException(status_code=404, detail="Trip has no assigned vehicle")

    try:
        return await fuel_cost_service.estimate_trip_cost(trip, trip.vehicle)
    except fuel_cost_service.MissingCostInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502, detail=f"ML service error: {exc.response.status_code} {exc.response.text}"
        )


@router.get("/{trip_id}/eta-prediction", response_model=MlEtaEstimate)
async def get_eta_prediction(trip_id: str, db: Session = Depends(get_db)):
    """Real ML-predicted ETA: expected_delay_xgboost_v1.pkl's regression on top
    of the trip's planned duration. Reuses the same 25-field feature
    engineering/validation as /predictions/delay."""
    trip = trip_service.get_trip(db, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    try:
        return await ml_eta_service.predict_ml_eta_for_trip(db, trip)
    except (
        delay_prediction_service.MissingFeatureDataError,
        delay_prediction_service.UnsupportedCategoryError,
        delay_prediction_service.InvalidFeatureRangeError,
    ) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502, detail=f"ML service error: {exc.response.status_code} {exc.response.text}"
        )
