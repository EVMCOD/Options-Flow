"""Initial schema — all 6 tables

Revision ID: 001
Revises:
Create Date: 2025-01-01 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # scanner_universe
    # ------------------------------------------------------------------ #
    op.create_table(
        "scanner_universe",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("priority", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("symbol", name="uq_scanner_universe_symbol"),
    )
    op.create_index("ix_scanner_universe_symbol", "scanner_universe", ["symbol"], unique=True)

    # ------------------------------------------------------------------ #
    # ingestion_runs
    # ------------------------------------------------------------------ #
    op.create_table(
        "ingestion_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'running'")),
        sa.Column("records_ingested", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # ------------------------------------------------------------------ #
    # raw_option_snapshots
    # ------------------------------------------------------------------ #
    op.create_table(
        "raw_option_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ingestion_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("raw_payload_json", postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_raw_option_snapshots_run_id", "raw_option_snapshots", ["run_id"])

    # ------------------------------------------------------------------ #
    # normalized_option_snapshots
    # ------------------------------------------------------------------ #
    op.create_table(
        "normalized_option_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("as_of_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("underlying_symbol", sa.String(20), nullable=False),
        sa.Column("expiry", sa.Date(), nullable=False),
        sa.Column("strike", sa.Numeric(10, 2), nullable=False),
        sa.Column("option_type", sa.String(1), nullable=False),
        sa.Column("spot_price", sa.Numeric(10, 4), nullable=False),
        sa.Column("bid", sa.Numeric(10, 4), nullable=False),
        sa.Column("ask", sa.Numeric(10, 4), nullable=False),
        sa.Column("last", sa.Numeric(10, 4), nullable=False),
        sa.Column("volume", sa.Integer(), nullable=False),
        sa.Column("open_interest", sa.Integer(), nullable=False),
        sa.Column("implied_vol", sa.Float(), nullable=True),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ingestion_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_normalized_option_snapshots_as_of_ts",
        "normalized_option_snapshots",
        ["as_of_ts"],
    )
    op.create_index(
        "ix_normalized_option_snapshots_underlying_symbol",
        "normalized_option_snapshots",
        ["underlying_symbol"],
    )
    op.create_index(
        "ix_normalized_option_snapshots_expiry",
        "normalized_option_snapshots",
        ["expiry"],
    )
    op.create_index(
        "ix_norm_snapshots_ts_symbol",
        "normalized_option_snapshots",
        ["as_of_ts", "underlying_symbol"],
    )

    # ------------------------------------------------------------------ #
    # signal_features
    # ------------------------------------------------------------------ #
    op.create_table(
        "signal_features",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "snapshot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("normalized_option_snapshots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("baseline_volume", sa.Float(), nullable=False),
        sa.Column("volume_ratio", sa.Float(), nullable=False),
        sa.Column("volume_zscore", sa.Float(), nullable=False),
        sa.Column("volume_oi_ratio", sa.Float(), nullable=True),
        sa.Column("premium_proxy", sa.Float(), nullable=True),
        sa.Column("iv_change", sa.Float(), nullable=True),
        sa.Column("anomaly_score", sa.Float(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("snapshot_id", name="uq_signal_features_snapshot_id"),
    )
    op.create_index(
        "ix_signal_features_snapshot_id", "signal_features", ["snapshot_id"], unique=True
    )

    # ------------------------------------------------------------------ #
    # alerts
    # ------------------------------------------------------------------ #
    op.create_table(
        "alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "snapshot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("normalized_option_snapshots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("underlying_symbol", sa.String(20), nullable=False),
        sa.Column("expiry", sa.Date(), nullable=False),
        sa.Column("strike", sa.Numeric(10, 2), nullable=False),
        sa.Column("option_type", sa.String(1), nullable=False),
        sa.Column("as_of_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("alert_level", sa.String(10), nullable=False),
        sa.Column("anomaly_score", sa.Float(), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_alerts_underlying_symbol", "alerts", ["underlying_symbol"])
    op.create_index("ix_alerts_as_of_ts", "alerts", ["as_of_ts"])
    op.create_index("ix_alerts_status", "alerts", ["status"])
    op.create_index("ix_alerts_created_at", "alerts", ["created_at"])


def downgrade() -> None:
    op.drop_table("alerts")
    op.drop_table("signal_features")
    op.drop_table("normalized_option_snapshots")
    op.drop_table("raw_option_snapshots")
    op.drop_table("ingestion_runs")
    op.drop_table("scanner_universe")
