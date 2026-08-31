"""Throwaway diagnostic: report alembic/schema state using ONE short-lived
connection (NullPool), so it can't contribute to Supabase's 15-session cap."""

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import NullPool

from app.core.config import settings

engine = create_engine(settings.DATABASE_URL, poolclass=NullPool)
inspector = inspect(engine)
names = set(inspector.get_table_names())

print("alembic_version exists:", "alembic_version" in names)
if "alembic_version" in names:
    with engine.connect() as conn:
        rows = [r[0] for r in conn.execute(text("select version_num from alembic_version"))]
    print("DB stamped at:", rows or "(empty)")

for t in [
    "routes", "route_stops", "trips", "vehicle_master", "driver_master",
    "delay_predictions", "hubs", "vehicle_dispatch_config",
    "driver_dispatch_config", "fuel_prices",
]:
    print("  %-26s %s" % (t, "EXISTS" if t in names else "missing"))

engine.dispose()
