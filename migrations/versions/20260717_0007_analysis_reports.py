"""Persist the latest structured portfolio analysis reports.

Revision ID: 20260717_0007
Revises: 20260715_0006
Create Date: 2026-07-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260717_0007"
down_revision: Union[str, None] = "20260715_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "analysis_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("model_status", sa.String(length=32), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_analysis_reports_source", "analysis_reports", ["source"])
    op.create_index("ix_analysis_reports_model_status", "analysis_reports", ["model_status"])
    op.create_index("ix_analysis_reports_generated_at", "analysis_reports", ["generated_at"])


def downgrade() -> None:
    op.drop_index("ix_analysis_reports_generated_at", table_name="analysis_reports")
    op.drop_index("ix_analysis_reports_model_status", table_name="analysis_reports")
    op.drop_index("ix_analysis_reports_source", table_name="analysis_reports")
    op.drop_table("analysis_reports")
