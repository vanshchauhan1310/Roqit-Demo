from datetime import timedelta

from sqlalchemy.orm import Session

from app.models.trip import Trip
from app.schemas.ml_eta import MlEtaEstimate
from app.services import delay_prediction_service, ml_client


async def predict_ml_eta_for_trip(db: Session, trip: Trip) -> MlEtaEstimate:
    """Reuses delay_prediction_service.engineer_features for the same
    validated 25-field payload the delay model uses, then calls the expected-
    delay regression model to get a real ML-predicted delivery time on top of
    the trip's planned duration."""
    features = delay_prediction_service.engineer_features(db, trip)
    result = await ml_client.predict_expected_delay(features)
    expected_delay_minutes = result["expected_delay_minutes"]

    predicted_delivery_time = (
        trip.pickup_time
        + timedelta(hours=features["planned_duration_hours"])
        + timedelta(minutes=expected_delay_minutes)
    )

    return MlEtaEstimate(
        trip_id=trip.trip_id,
        planned_duration_hours=features["planned_duration_hours"],
        expected_delay_minutes=expected_delay_minutes,
        predicted_delivery_time=predicted_delivery_time,
    )
