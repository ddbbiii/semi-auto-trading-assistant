"""Create persistent opportunity watchlist.

Revision ID: 20260713_0002
Revises: 20260713_0001
Create Date: 2026-07-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260713_0002"
down_revision: Union[str, None] = "20260713_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "opportunity_watchlist",
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=120), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("symbol"),
    )
    op.create_index("ix_opportunity_watchlist_position", "opportunity_watchlist", ["position"])


def downgrade() -> None:
    op.drop_index("ix_opportunity_watchlist_position", table_name="opportunity_watchlist")
    op.drop_table("opportunity_watchlist")
