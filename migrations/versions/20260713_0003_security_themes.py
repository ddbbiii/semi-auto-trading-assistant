"""Create persistent security theme classifications.

Revision ID: 20260713_0003
Revises: 20260713_0002
Create Date: 2026-07-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260713_0003"
down_revision: Union[str, None] = "20260713_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "security_themes",
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("theme", sa.String(length=80), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("symbol"),
    )
    op.create_index("ix_security_themes_theme", "security_themes", ["theme"])


def downgrade() -> None:
    op.drop_index("ix_security_themes_theme", table_name="security_themes")
    op.drop_table("security_themes")
