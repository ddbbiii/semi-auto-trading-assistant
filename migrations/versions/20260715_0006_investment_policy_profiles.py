"""Expand holding profiles for the investment decision framework.

Revision ID: 20260715_0006
Revises: 20260713_0005
Create Date: 2026-07-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260715_0006"
down_revision: Union[str, None] = "20260713_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TEXT_COLUMNS = (
    "thesis_summary",
    "strongest_bear_case",
    "buy_add_conditions",
    "reduce_conditions",
    "exit_invalidation_conditions",
    "bear_scenario",
    "base_scenario",
    "bull_scenario",
)


def upgrade() -> None:
    for name in TEXT_COLUMNS:
        op.add_column("holding_risk_profiles", sa.Column(name, sa.Text(), nullable=True))
    op.add_column(
        "holding_risk_profiles",
        sa.Column("information_grade", sa.String(length=16), server_default="unrated", nullable=False),
    )
    op.add_column(
        "holding_risk_profiles",
        sa.Column("research_confidence", sa.String(length=16), server_default="unrated", nullable=False),
    )
    op.add_column(
        "holding_risk_profiles",
        sa.Column("investment_certainty", sa.String(length=16), server_default="unrated", nullable=False),
    )
    op.add_column(
        "holding_risk_profiles",
        sa.Column("position_intent", sa.String(length=24), server_default="long_term", nullable=False),
    )
    op.add_column(
        "holding_risk_profiles",
        sa.Column("price_response", sa.String(length=24), server_default="review", nullable=False),
    )


def downgrade() -> None:
    for name in ("price_response", "position_intent", "investment_certainty", "research_confidence", "information_grade"):
        op.drop_column("holding_risk_profiles", name)
    for name in reversed(TEXT_COLUMNS):
        op.drop_column("holding_risk_profiles", name)
