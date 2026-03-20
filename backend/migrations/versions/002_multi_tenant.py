"""Multi-tenant foundation

Adds Tenant and TenantProviderConfig tables.
Adds tenant_id FK columns to scanner_universe, ingestion_runs, and alerts.
Changes the unique constraint on scanner_universe.symbol to be per-tenant.

Existing data is backfilled to the default system tenant
(00000000-0000-0000-0000-000000000001).

Revision ID: 002
Revises: 001
Create Date: 2025-01-02 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The default tenant UUID is fixed so migrations and application code share
# a single source of truth without a runtime lookup.
DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # tenants
    # ------------------------------------------------------------------ #
    op.create_table(
        "tenants",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("slug", sa.String(50), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("slug", name="uq_tenants_slug"),
    )
    op.create_index("ix_tenants_slug", "tenants", ["slug"], unique=True)

    # ------------------------------------------------------------------ #
    # tenant_provider_configs
    # ------------------------------------------------------------------ #
    op.create_table(
        "tenant_provider_configs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider_type", sa.String(50), nullable=False),
        sa.Column(
            "credentials_json",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
        sa.Column(
            "config_json",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_tenant_provider_configs_tenant_id",
        "tenant_provider_configs",
        ["tenant_id"],
    )

    # ------------------------------------------------------------------ #
    # Seed the default system tenant and its mock provider config
    # ------------------------------------------------------------------ #
    op.execute(f"""
        INSERT INTO tenants (id, name, slug, is_active, created_at)
        VALUES (
            '{DEFAULT_TENANT_ID}',
            'Default Workspace',
            'default',
            true,
            now()
        )
    """)

    op.execute(f"""
        INSERT INTO tenant_provider_configs
            (id, tenant_id, provider_type, credentials_json, config_json, is_active, created_at)
        VALUES (
            gen_random_uuid(),
            '{DEFAULT_TENANT_ID}',
            'mock',
            '{{}}',
            '{{}}',
            true,
            now()
        )
    """)

    # ------------------------------------------------------------------ #
    # scanner_universe — add tenant_id, change unique constraint
    # ------------------------------------------------------------------ #
    op.add_column(
        "scanner_universe",
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_scanner_universe_tenant_id", "scanner_universe", ["tenant_id"])

    # Backfill existing rows to the default tenant
    op.execute(f"UPDATE scanner_universe SET tenant_id = '{DEFAULT_TENANT_ID}'")

    # Replace the global unique index with a per-tenant unique constraint
    op.drop_index("ix_scanner_universe_symbol", table_name="scanner_universe")
    op.drop_constraint("uq_scanner_universe_symbol", "scanner_universe", type_="unique")
    op.create_unique_constraint(
        "uq_scanner_universe_symbol_tenant",
        "scanner_universe",
        ["symbol", "tenant_id"],
    )
    # Keep a non-unique index on symbol alone for lookup performance
    op.create_index("ix_scanner_universe_symbol", "scanner_universe", ["symbol"])

    # ------------------------------------------------------------------ #
    # ingestion_runs — add tenant_id
    # ------------------------------------------------------------------ #
    op.add_column(
        "ingestion_runs",
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_ingestion_runs_tenant_id", "ingestion_runs", ["tenant_id"])
    op.execute(f"UPDATE ingestion_runs SET tenant_id = '{DEFAULT_TENANT_ID}'")

    # ------------------------------------------------------------------ #
    # alerts — add tenant_id (denormalised for query performance)
    # ------------------------------------------------------------------ #
    op.add_column(
        "alerts",
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_alerts_tenant_id", "alerts", ["tenant_id"])
    op.execute(f"UPDATE alerts SET tenant_id = '{DEFAULT_TENANT_ID}'")


def downgrade() -> None:
    # Reverse order of dependencies

    op.drop_index("ix_alerts_tenant_id", table_name="alerts")
    op.drop_column("alerts", "tenant_id")

    op.drop_index("ix_ingestion_runs_tenant_id", table_name="ingestion_runs")
    op.drop_column("ingestion_runs", "tenant_id")

    # Restore scanner_universe to global unique on symbol
    op.drop_constraint("uq_scanner_universe_symbol_tenant", "scanner_universe", type_="unique")
    op.drop_index("ix_scanner_universe_symbol", table_name="scanner_universe")
    op.drop_index("ix_scanner_universe_tenant_id", table_name="scanner_universe")
    op.drop_column("scanner_universe", "tenant_id")
    op.create_unique_constraint("uq_scanner_universe_symbol", "scanner_universe", ["symbol"])
    op.create_index("ix_scanner_universe_symbol", "scanner_universe", ["symbol"], unique=True)

    op.drop_index("ix_tenant_provider_configs_tenant_id", table_name="tenant_provider_configs")
    op.drop_table("tenant_provider_configs")

    op.drop_index("ix_tenants_slug", table_name="tenants")
    op.drop_table("tenants")
