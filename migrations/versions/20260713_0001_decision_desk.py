"""Create decision desk storage.

Revision ID: 20260713_0001
Revises:
Create Date: 2026-07-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260713_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "portfolio_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("account_json", sa.Text(), nullable=False),
        sa.Column("pending_order_count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_portfolio_snapshots_as_of", "portfolio_snapshots", ["as_of"])
    op.create_table(
        "holdings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("snapshot_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["snapshot_id"], ["portfolio_snapshots.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_holdings_snapshot_id", "holdings", ["snapshot_id"])
    op.create_index("ix_holdings_symbol", "holdings", ["symbol"])
    op.create_table(
        "decisions",
        sa.Column("id", sa.String(length=80), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("priority", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    for name in ("symbol", "priority", "status", "generated_at", "expires_at"):
        op.create_index(f"ix_decisions_{name}", "decisions", [name])
    op.create_table(
        "decision_feedback",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("decision_id", sa.String(length=80), nullable=False),
        sa.Column("action", sa.String(length=24), nullable=False),
        sa.Column("executed_quantity", sa.Float(), nullable=True),
        sa.Column("executed_price", sa.Float(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["decision_id"], ["decisions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_decision_feedback_decision_id", "decision_feedback", ["decision_id"])
    op.create_table(
        "sync_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sync_runs_source", "sync_runs", ["source"])
    op.create_index("ix_sync_runs_status", "sync_runs", ["status"])
    op.create_table(
        "quotes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    for name in ("symbol", "provider", "observed_at"):
        op.create_index(f"ix_quotes_{name}", "quotes", [name])
    op.create_table(
        "fx_rates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("rate_to_cny", sa.Float(), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_fx_rates_currency", "fx_rates", ["currency"])
    op.create_index("ix_fx_rates_observed_at", "fx_rates", ["observed_at"])
    op.create_table(
        "evidence_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    for name in ("symbol", "kind", "observed_at"):
        op.create_index(f"ix_evidence_events_{name}", "evidence_events", [name])
    op.create_table(
        "import_runs",
        sa.Column("id", sa.String(length=80), nullable=False),
        sa.Column("parser", sa.String(length=32), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("holding_count", sa.Integer(), nullable=False),
        sa.Column("warnings_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_import_runs_status", "import_runs", ["status"])


def downgrade() -> None:
    op.drop_table("import_runs")
    op.drop_table("evidence_events")
    op.drop_table("fx_rates")
    op.drop_table("quotes")
    op.drop_table("sync_runs")
    op.drop_table("decision_feedback")
    op.drop_table("decisions")
    op.drop_table("holdings")
    op.drop_table("portfolio_snapshots")
