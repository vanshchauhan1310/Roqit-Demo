from datetime import datetime

from sqlalchemy.orm import Session

from app.models.gps_breadcrumb import GpsBreadcrumb
from app.models.realtime_fleet_status import RealtimeFleetStatus
from app.models.trip import Trip
from app.schemas.realtime import RealtimeLiveRead


def get_live_status(db: Session, trip: Trip) -> RealtimeLiveRead:
    """Live telemetry for a trip: the fleet-status row for its vehicle
    (the newest GPS event per vehicle) plus the latest breadcrumb recorded
    for the trip itself."""
    breadcrumbs = (
        db.query(GpsBreadcrumb)
        .filter(GpsBreadcrumb.trip_id == trip.trip_id)
        .order_by(GpsBreadcrumb.timestamp.desc())
        .limit(1)
        .all()
    )
    latest = breadcrumbs[0] if breadcrumbs else None

    fleet = None
    if trip.vehicle_id:
        fleet = db.get(RealtimeFleetStatus, trip.vehicle_id)

    return RealtimeLiveRead(
        trip_id=trip.trip_id,
        status=trip.status,
        vehicle_id=trip.vehicle_id,
        vehicle_status=fleet.status if fleet else None,
        current_lat=fleet.current_lat if fleet else None,
        current_lon=fleet.current_lon if fleet else None,
        current_speed_kmph=fleet.current_speed_kmph if fleet else None,
        alert_flag=fleet.alert_flag if fleet else None,
        last_updated=fleet.last_updated if fleet else None,
        breadcrumb_count=(
            db.query(GpsBreadcrumb).filter(GpsBreadcrumb.trip_id == trip.trip_id).count()
        ),
        latest_speed_kmph=latest.speed_kmph if latest else None,
        latest_heading_deg=latest.heading_deg if latest else None,
        latest_timestamp=latest.timestamp if latest else None,
    )
