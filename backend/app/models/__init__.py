# Import all models here so Base.metadata (and Alembic autogenerate) picks
# them up, and so any first touch of a single model module - e.g.
# `from app.models.trip import Trip` from a service file - doesn't race
# app.db.base's own model registration and hit a circular import.
#
# This file, not app/db/base.py, owns that registration: app.db.base only
# defines Base and imports nothing from app.models, so there is exactly one
# direction of dependency (models -> db.base), never the reverse.
from app.models.trip import Trip  # noqa: E402,F401
from app.models.route import Route, RouteStop  # noqa: E402,F401
from app.models.vehicle import Vehicle  # noqa: E402,F401
from app.models.driver import Driver  # noqa: E402,F401
from app.models.gps_breadcrumb import GpsBreadcrumb  # noqa: E402,F401
from app.models.maintenance_event import MaintenanceEvent  # noqa: E402,F401
from app.models.driver_hours import DriverHours  # noqa: E402,F401
from app.models.realtime_fleet_status import RealtimeFleetStatus  # noqa: E402,F401
from app.models.delay_prediction import DelayPrediction  # noqa: E402,F401
