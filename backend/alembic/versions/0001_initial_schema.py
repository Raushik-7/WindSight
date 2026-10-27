"""Initial schema: observations + import audit trail

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-26
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "actual_generation",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("dataset", sa.String(length=32), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("generation_mw", sa.Float(), nullable=False),
        sa.Column("publish_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("settlement_date", sa.String(length=16), nullable=True),
        sa.Column("settlement_period", sa.Integer(), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_actual_generation")),
        sa.UniqueConstraint("dataset", "start_time", name="uq_actual_dataset_interval"),
    )
    op.create_index(
        "ix_actual_generation_start_time", "actual_generation", ["start_time"], unique=False
    )

    op.create_table(
        "wind_forecasts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("dataset", sa.String(length=32), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("publish_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("generation_mw", sa.Float(), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_wind_forecasts")),
        sa.UniqueConstraint(
            "dataset", "start_time", "publish_time", name="uq_forecast_dataset_interval_publish"
        ),
    )
    op.create_index(
        "ix_wind_forecasts_start_publish",
        "wind_forecasts",
        ["start_time", "publish_time"],
        unique=False,
    )
    op.create_index("ix_wind_forecasts_publish_time", "wind_forecasts", ["publish_time"], unique=False)

    op.create_table(
        "data_import_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("dataset", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("range_kind", sa.String(length=32), nullable=False),
        sa.Column("range_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("range_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("records_retrieved", sa.Integer(), nullable=False),
        sa.Column("records_inserted", sa.Integer(), nullable=False),
        sa.Column("records_updated", sa.Integer(), nullable=False),
        sa.Column("windows_total", sa.Integer(), nullable=False),
        sa.Column("windows_ok", sa.Integer(), nullable=False),
        sa.Column("windows_failed_json", sa.Text(), nullable=False),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("coverage_verified", sa.Boolean(), nullable=False),
        sa.Column("coverage_detail", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_data_import_runs")),
    )
    op.create_index(
        "ix_import_runs_dataset_started",
        "data_import_runs",
        ["dataset", "started_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_import_runs_dataset_started", table_name="data_import_runs")
    op.drop_table("data_import_runs")
    op.drop_index("ix_wind_forecasts_publish_time", table_name="wind_forecasts")
    op.drop_index("ix_wind_forecasts_start_publish", table_name="wind_forecasts")
    op.drop_table("wind_forecasts")
    op.drop_index("ix_actual_generation_start_time", table_name="actual_generation")
    op.drop_table("actual_generation")
