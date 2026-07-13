"""Create configurable portfolio risk settings and holding profiles.

Revision ID: 20260713_0005
Revises: 20260713_0004
Create Date: 2026-07-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260713_0005"
down_revision: Union[str, None] = "20260713_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "risk_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("max_single_position_percent", sa.Float(), nullable=False),
        sa.Column("daily_move_alert_percent", sa.Float(), nullable=False),
        sa.Column("warrant_expiry_warning_days", sa.Integer(), nullable=False),
        sa.Column("target_weight_tolerance_percent", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        sa.text(
            "INSERT INTO risk_settings "
            "(id, max_single_position_percent, daily_move_alert_percent, warrant_expiry_warning_days, "
            "target_weight_tolerance_percent, updated_at) "
            "VALUES (1, 25, 8, 30, 2, CURRENT_TIMESTAMP)"
        )
    )
    op.create_table(
        "holding_risk_profiles",
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("stop_price", sa.Float(), nullable=True),
        sa.Column("target_weight_percent", sa.Float(), nullable=True),
        sa.Column("thesis_invalidation", sa.Text(), nullable=True),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("activation_snapshot_id", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("symbol"),
    )
    op.create_index("ix_holding_risk_profiles_status", "holding_risk_profiles", ["status"])


def downgrade() -> None:
    op.drop_index("ix_holding_risk_profiles_status", table_name="holding_risk_profiles")
    op.drop_table("holding_risk_profiles")
    op.drop_table("risk_settings")
