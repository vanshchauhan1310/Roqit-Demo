from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# Import all models here so Alembic autogenerate and Base.metadata pick them up.
from app.models.trip import Trip  # noqa: E402,F401
from app.models.route import Route, RouteStop  # noqa: E402,F401
from app.models.vehicle import Vehicle  # noqa: E402,F401
from app.models.driver import Driver  # noqa: E402,F401
from app.models.gps_breadcrumb import GpsBreadcrumb  # noqa: E402,F401
from app.models.maintenance_event import MaintenanceEvent  # noqa: E402,F401
from app.models.driver_hours import DriverHours  # noqa: E402,F401
