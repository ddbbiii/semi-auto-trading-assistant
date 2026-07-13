"""Create configurable analysis schedule settings.

Revision ID: 20260713_0004
Revises: 20260713_0003
Create Date: 2026-07-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260713_0004"
down_revision: Union[str, None] = "20260713_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "analysis_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("interval_minutes", sa.Integer(), nullable=False),
        sa.Column("analyze_us_premarket", sa.Boolean(), nullable=False),
        sa.Column("analyze_regular_session", sa.Boolean(), nullable=False),
        sa.Column("analyze_us_afterhours", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        sa.text(
            "INSERT INTO analysis_settings "
            "(id, interval_minutes, analyze_us_premarket, analyze_regular_session, analyze_us_afterhours, updated_at) "
            "VALUES (1, 120, 0, 1, 0, CURRENT_TIMESTAMP)"
        )
    )


def downgrade() -> None:
    op.drop_table("analysis_settings")
