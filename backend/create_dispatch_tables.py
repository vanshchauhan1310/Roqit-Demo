"""Creates the four dispatch-config tables directly from their model metadata.

WHY THIS EXISTS INSTEAD OF `alembic upgrade`
--------------------------------------------
This database is stamped at alembic revision 2a6f9c1d4b7e, which exists in no
commit and no branch of this repository - the migration file that produced it was
never committed (or was deleted). Alembic therefore cannot run here at all:
`upgrade` aborts with "Can't locate revision identified by '2a6f9c1d4b7e'", and
`stamp`-ing over it would silently discard the record of whatever that migration
applied.

Rather than corrupt the existing migration state, this script creates only the
four NEW tables, with checkfirst=True so it is safe to re-run and cannot touch
anything that already exists. `alembic_version` is deliberately left alone.

The migration file (c9d0e1f2a3b4) remains the source of truth for any clean
environment - this script is the workaround for THIS database's broken lineage,
not a replacement for it. Resolving the missing revision is a separate task.

Usage, from backend/ with its venv active:
    python create_dispatch_tables.py
"""

from sqlalchemy import create_engine, inspect
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.db.base import Base
from app.models.dispatch_config import DriverDispatchConfig, FuelPrice, VehicleDispatchConfig
from app.models.hub import Hub

# Only these. Never Base.metadata.create_all() wholesale - that would try to
# create every model's table, including the CSV-imported masters this app must
# not touch (see migration a1b2c3d4e5f6's own note).
TARGET_TABLES = [
    Hub.__table__,
    VehicleDispatchConfig.__table__,
    DriverDispatchConfig.__table__,
    FuelPrice.__table__,
]


def main() -> None:
    engine = create_engine(settings.DATABASE_URL, poolclass=NullPool)
    try:
        before = set(inspect(engine).get_table_names())
        missing = [t for t in TARGET_TABLES if t.name not in before]

        if not missing:
            print("All four dispatch tables already exist - nothing to do.")
            return

        print("Creating:", ", ".join(t.name for t in missing))
        # create_all sorts by FK dependency, so hubs lands before the tables
        # that reference it.
        Base.metadata.create_all(engine, tables=missing, checkfirst=True)

        after = set(inspect(engine).get_table_names())
        for t in TARGET_TABLES:
            status = "created" if t.name in after and t.name not in before else (
                "already existed" if t.name in before else "FAILED"
            )
            print(f"  {t.name:26s} {status}")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
