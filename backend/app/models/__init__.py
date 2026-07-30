# Import all models here so Base.metadata (and Alembic autogenerate) pick them up
# without db/base.py needing to import back into app.models, which would be circular.
from app.models.trip import Trip  # noqa: F401
from app.models.route import Route, RouteStop  # noqa: F401
from app.models.vehicle import Vehicle  # noqa: F401
from app.models.driver import Driver  # noqa: F401
from app.models.gps_breadcrumb import GpsBreadcrumb  # noqa: F401
from app.models.maintenance_event import MaintenanceEvent  # noqa: F401
from app.models.driver_hours import DriverHours  # noqa: F401
from app.models.driver_master import DriverMaster  # noqa: F401
from app.models.vehicle_master import VehicleMaster  # noqa: F401
from app.models.realtime_fleet_status import RealtimeFleetStatus  # noqa: F401
