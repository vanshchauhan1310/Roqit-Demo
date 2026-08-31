"""add_optimization_fields_and_audit_tables

Revision ID: a86ca6923361
Revises: b43192b98712
Create Date: 2026-08-27 17:49:18.351226

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = 'a86ca6923361'
down_revision: Union[str, None] = 'b43192b98712'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add optimization fields to routes table
    op.add_column("routes", sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False))
    op.add_column("routes", sa.Column("version", sa.Integer(), server_default="0", nullable=False))
    op.add_column("routes", sa.Column("frozen_until_sequence", sa.Integer(), server_default="0", nullable=False))
    op.add_column("routes", sa.Column("total_distance_km", sa.Float(), nullable=True))
    op.add_column("routes", sa.Column("planned_distance_km", sa.Float(), nullable=True))
    op.add_column("routes", sa.Column("estimated_duration_minutes", sa.BigInteger(), nullable=True))
    op.add_column("routes", sa.Column("remaining_duration_minutes", sa.BigInteger(), nullable=True))
    op.add_column("routes", sa.Column("capacity_kg", sa.Float(), nullable=True))
    op.add_column("routes", sa.Column("used_capacity_kg", sa.Float(), nullable=True))
    op.add_column("routes", sa.Column("remaining_capacity_kg", sa.Float(), nullable=True))
    op.add_column("routes", sa.Column("delay_risk", sa.Float(), nullable=True))
    op.add_column("routes", sa.Column("route_score", sa.Float(), nullable=True))
    op.add_column("routes", sa.Column("current_lat", sa.Float(), nullable=True))
    op.add_column("routes", sa.Column("current_lon", sa.Float(), nullable=True))

    # Create route_assignments table
    op.create_table(
        "route_assignments",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("trip_id", sa.String(), sa.ForeignKey("trips.trip_id"), nullable=False),
        sa.Column("route_id", UUID(as_uuid=True), sa.ForeignKey("routes.route_id"), nullable=False),
        sa.Column("assignment_status", sa.String(length=20), nullable=False),
        sa.Column("insertion_position", sa.Integer(), nullable=True),
        sa.Column("additional_distance_km", sa.Float(), nullable=True),
        sa.Column("additional_duration_minutes", sa.Float(), nullable=True),
        sa.Column("delay_impact_minutes", sa.Float(), nullable=True),
        sa.Column("fuel_cost_rupees", sa.Float(), nullable=True),
        sa.Column("delay_risk", sa.Float(), nullable=True),
        sa.Column("change_penalty", sa.Float(), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("algorithm", sa.String(length=50), nullable=False),
        sa.Column("algorithm_version", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_route_assignments_trip_id", "route_assignments", ["trip_id"])
    op.create_index("ix_route_assignments_route_id", "route_assignments", ["route_id"])

    # Create optimization_runs table
    op.create_table(
        "optimization_runs",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("optimization_type", sa.String(length=20), nullable=False),
        sa.Column("trip_id", sa.String(), sa.ForeignKey("trips.trip_id"), nullable=True),
        sa.Column("candidate_routes_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("feasible_routes_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("routes_affected", sa.Integer(), server_default="0", nullable=False),
        sa.Column("old_cost", sa.Float(), nullable=True),
        sa.Column("new_cost", sa.Float(), nullable=True),
        sa.Column("improvement", sa.Float(), nullable=True),
        sa.Column("execution_time_ms", sa.Integer(), server_default="0", nullable=False),
        sa.Column("algorithm_version", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="completed", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_optimization_runs_trip_id", "optimization_runs", ["trip_id"])
    op.create_index("ix_optimization_runs_optimization_type", "optimization_runs", ["optimization_type"])


def downgrade() -> None:
    op.drop_index("ix_optimization_runs_optimization_type", table_name="optimization_runs")
    op.drop_index("ix_optimization_runs_trip_id", table_name="optimization_runs")
    op.drop_table("optimization_runs")

    op.drop_index("ix_route_assignments_route_id", table_name="route_assignments")
    op.drop_index("ix_route_assignments_trip_id", table_name="route_assignments")
    op.drop_table("route_assignments")

    op.drop_column("routes", "current_lon")
    op.drop_column("routes", "current_lat")
    op.drop_column("routes", "route_score")
    op.drop_column("routes", "delay_risk")
    op.drop_column("routes", "remaining_capacity_kg")
    op.drop_column("routes", "used_capacity_kg")
    op.drop_column("routes", "capacity_kg")
    op.drop_column("routes", "remaining_duration_minutes")
    op.drop_column("routes", "estimated_duration_minutes")
    op.drop_column("routes", "planned_distance_km")
    op.drop_column("routes", "total_distance_km")
    op.drop_column("routes", "frozen_until_sequence")
    op.drop_column("routes", "version")
    op.drop_column("routes", "updated_at")