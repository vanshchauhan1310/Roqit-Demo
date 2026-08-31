"""Check trips table columns for route_id / driver_id / vehicle_id and RouteStop."""
from sqlalchemy import create_engine, text
from app.core.config import settings

e = create_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_size=2, max_overflow=2)
c = e.connect()
try:
    cols = c.execute(text(
        "SELECT column_name FROM information_schema.columns WHERE table_name='trips' ORDER BY ordinal_position"
    )).fetchall()
    print("trips columns:", [r[0] for r in cols])
    print()
    print("Has route_id?", any(r[0] == 'route_id' for r in cols))
except Exception as exc:
    print("ERR:", type(exc).__name__, exc)
c.close()
e.dispose()
"""Diagnostic: check alembic version + optimization tables in the live DB."""
from sqlalchemy import create_engine, text
from app.core.config import settings

e = create_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_size=2, max_overflow=2)
c = e.connect()

try:
    rows = c.execute(text("SELECT version_num FROM alembic_version")).fetchall()
    print("alembic_version:", rows)
except Exception as exc:
    print("alembic_version query failed:", type(exc).__name__, exc)

try:
    t = c.execute(text(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='public' AND table_name IN "
        "('route_assignments','optimization_runs','routes','trips','driver_master','vehicle_master')"
    )).fetchall()
    print("tables found:", [r[0] for r in t])
except Exception as exc:
    print("tables query failed:", type(exc).__name__, exc)

try:
    cols = c.execute(text(
        "SELECT column_name FROM information_schema.columns WHERE table_name='routes' "
        "AND column_name IN ('version','frozen_until_sequence','capacity_kg','used_capacity_kg',"
        "'remaining_capacity_kg','delay_risk','route_score','current_lat','current_lon')"
    )).fetchall()
    print("routes optimization columns:", sorted(r[0] for r in cols))
except Exception as exc:
    print("columns query failed:", type(exc).__name__, exc)

c.close()
e.dispose()