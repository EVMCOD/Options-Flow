"""Provider hardening and ingestion run observability

Adds to tenant_provider_configs:
  - is_default (bool, default false)
  - status (varchar 20, default 'unknown')
  - last_healthy_at (timestamptz, nullable)
  - last_error (text, nullable)
  - updated_at (timestamptz, server default now())
  - Partial unique index ix_tpc_one_default_per_tenant

Adds to ingestion_runs:
  - provider_config_id (uuid FK → tenant_provider_configs, SET NULL)
  - provider_type (varchar 50, nullable)

Revision ID: 003
Revises: 002
Create Date: 2025-01-03 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -----------------------------------------------------------------------
    # tenant_provider_configs — new operational/health columns
    # -----------------------------------------------------------------------
    op.add_column(
        "tenant_provider_configs",
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "tenant_provider_configs",
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'unknown'"),
        ),
    )
    op.add_column(
        "tenant_provider_configs",
        sa.Column("last_healthy_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "tenant_provider_configs",
        sa.Column("last_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "tenant_provider_configs",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Partial unique index: only one is_default=true per tenant.
    op.create_index(
        "ix_tpc_one_default_per_tenant",
        "tenant_provider_configs",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("is_default = true"),
    )

    # -----------------------------------------------------------------------
    # ingestion_runs — provider auditability columns
    # -----------------------------------------------------------------------
    op.add_column(
        "ingestion_runs",
        sa.Column(
            "provider_config_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenant_provider_configs.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_ingestion_runs_provider_config_id",
        "ingestion_runs",
        ["provider_config_id"],
    )
    op.add_column(
        "ingestion_runs",
        sa.Column("provider_type", sa.String(50), nullable=True),
    )


def downgrade() -> None:
    # ingestion_runs
    op.drop_index("ix_ingestion_runs_provider_config_id", table_name="ingestion_runs")
    op.drop_column("ingestion_runs", "provider_type")
    op.drop_column("ingestion_runs", "provider_config_id")

    # tenant_provider_configs
    op.drop_index("ix_tpc_one_default_per_tenant", table_name="tenant_provider_configs")
    op.drop_column("tenant_provider_configs", "updated_at")
    op.drop_column("tenant_provider_configs", "last_error")
    op.drop_column("tenant_provider_configs", "last_healthy_at")
    op.drop_column("tenant_provider_configs", "status")
    op.drop_column("tenant_provider_configs", "is_default")
