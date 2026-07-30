import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.delay_prediction import DelayPredictionRead
from app.services import delay_prediction_service, trip_service

router = APIRouter(prefix="/predictions/delay", tags=["predictions"])


@router.post("/latest", response_model=DelayPredictionRead)
async def predict_delay_for_latest_trip(db: Session = Depends(get_db)):
    """Full pipeline entry point: Fetch Latest Trip (by most recently updated
    realtime_fleet_status row) -> Engineer Features -> Predict -> Store Prediction -> return JSON."""
    trip = trip_service.get_latest_trip_by_gps_activity(db)
    if trip is None:
        raise HTTPException(status_code=404, detail="No vehicles with an active trip found")
    return await _run_pipeline(db, trip)


@router.post("/trips/{trip_id}", response_model=DelayPredictionRead)
async def predict_delay_for_trip(trip_id: str, db: Session = Depends(get_db)):
    trip = trip_service.get_trip(db, trip_id)
    if trip is None:
        raise HTTPException(status_code=404, detail="Trip not found")
    return await _run_pipeline(db, trip)


async def _run_pipeline(db: Session, trip):
    try:
        return await delay_prediction_service.predict_delay_for_trip(db, trip)
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
