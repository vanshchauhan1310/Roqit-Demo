import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.delay_prediction import DelayPredictionRead, ExpectedDelayRead
from app.services import delay_prediction_service, trip_service

router = APIRouter(prefix="/predictions/delay", tags=["predictions"])
expected_delay_router = APIRouter(prefix="/predictions/expected-delay", tags=["predictions"])


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


@router.post("/fleet")
def predict_delay_for_fleet():
    """On-demand fleet-wide prediction sweep: re-predicts every ACTIVE trip
    (route assigned, not yet delivered) across ALL routes, up to
    PREDICTION_MAX_TRIPS_PER_RUN per pass. The same code path the 3-trip milestone
    trigger uses - useful right after seeding/backfilling data, when you want
    100% coverage immediately instead of waiting for the next completion
    milestone.

    Sync def on purpose: the helper calls asyncio.run() per trip internally,
    which requires a thread without a running event loop (FastAPI runs sync
    endpoints in a threadpool). Returns {predicted, skipped_failed}.
    """
    from app.workers.trip_completion_worker import (
        PREDICTION_MAX_TRIPS_PER_RUN,
        _repredict_route_trips,
    )

    done: set[str] = set()
    predicted = failed = 0
    while True:
        pass_predicted, pass_failed = _repredict_route_trips(exclude_ids=done)
        predicted += pass_predicted
        failed += pass_failed
        # Each pass pulls at most PREDICTION_MAX_TRIPS_PER_RUN trips; when a
        # pass finds fewer than the cap, the eligible pool is exhausted, so
        # stop looping and report totals.
        if pass_predicted + pass_failed < PREDICTION_MAX_TRIPS_PER_RUN:
            break
    return {"predicted": predicted, "skipped_failed": failed}


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


@expected_delay_router.post("/trips/{trip_id}", response_model=ExpectedDelayRead)
async def predict_expected_delay_for_trip(trip_id: str, db: Session = Depends(get_db)):
    trip = trip_service.get_trip(db, trip_id)
    if trip is None:
        raise HTTPException(status_code=404, detail="Trip not found")
    try:
        result = await delay_prediction_service.predict_expected_delay_for_trip(db, trip)
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
    return ExpectedDelayRead(**result)
