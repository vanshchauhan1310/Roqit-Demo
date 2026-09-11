"""Baseline: create the full schema from the current SQLAlchemy models.

Revision ID: 0001_baseline
Revises: 000000000000
Create Date: 2026-09-01

Why a single baseline:
    The previous migration history was unrecoverable. Its root revisions
    (``000000000000`` and ``3bd8ab2c9348``) were never committed to this
    repository, so ``alembic upgrade head`` crashed on any fresh database
    with ``KeyError: '000000000000'`` — and even with the graph repaired,
    the orphaned 4f1a2b3c4d5e chain (route assignment columns,
    route_stops.trip_id, trips.assigned_at) could never be applied on the
    main line, leaving the schema incomplete.

    The old files are kept for reference in
    ``docs/_archived_broken_migrations/`` (outside the Docker build
    context; alembic only scans ``versions/``).

How this migration works:
    It creates every table exactly as the SQLAlchemy models define them
    (``app/models`` is the single source of truth) via
    ``Base.metadata.create_all`` — no drift between models and schema is
    possible by construction.

Existing databases:
    If you have a database built before this change (e.g. the Supabase dev
    DB), do NOT run this migration — just stamp it:
        alembic stamp head
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0001_baseline"
down_revision: Union[str, None] = "000000000000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from app.db.base import Base
    import app.models  # noqa: F401 - registers every table on Base.metadata

    # create_all orders tables by FK dependency automatically.
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    from app.db.base import Base
    import app.models  # noqa: F401

    Base.metadata.drop_all(bind=op.get_bind())
