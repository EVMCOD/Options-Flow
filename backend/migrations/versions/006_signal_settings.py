"""
006 — Hierarchical signal settings.

Adds two tables:
  tenant_signal_settings  — per-tenant signal defaults (one row per tenant)
  tenant_symbol_settings  — per-symbol signal overrides (one row per tenant+symbol)

All signal-threshold columns are nullable. Null means "inherit from the
next layer" (symbol → tenant → global config.py defaults).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_signal_settings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("min_premium_proxy", sa.Float(), nullable=True),
        sa.Column("max_dte_days", sa.Integer(), nullable=True),
        sa.Column("max_moneyness_pct", sa.Float(), nullable=True),
        sa.Column("min_open_interest", sa.Integer(), nullable=True),
        sa.Column("min_alert_level", sa.String(10), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_tenant_signal_settings_tenant_id", "tenant_signal_settings", ["tenant_id"])

    op.create_table(
        "tenant_symbol_settings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("min_premium_proxy", sa.Float(), nullable=True),
        sa.Column("max_dte_days", sa.Integer(), nullable=True),
        sa.Column("max_moneyness_pct", sa.Float(), nullable=True),
        sa.Column("min_open_interest", sa.Integer(), nullable=True),
        sa.Column("min_alert_level", sa.String(10), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("tenant_id", "symbol", name="uq_tenant_symbol_settings"),
    )
    op.create_index("ix_tenant_symbol_settings_tenant_id", "tenant_symbol_settings", ["tenant_id"])
    op.create_index("ix_tenant_symbol_settings_symbol", "tenant_symbol_settings", ["symbol"])


def downgrade() -> None:
    op.drop_table("tenant_symbol_settings")
    op.drop_table("tenant_signal_settings")
