"""008_alert_deduplication

Add deduplication and cooldown support to the alerts pipeline.

  alerts:
    - dedupe_key           VARCHAR(255) nullable, indexed
        Composite key: {tenant_id}:{symbol}:{expiry}:{strike}:{option_type}:{level}
        Used to locate the canonical alert for a contract+level combination during
        cooldown suppression. Pattern type appended when detected.
    - duplicate_count      INTEGER NOT NULL DEFAULT 0
        How many same-key alerts were suppressed while this alert was in cooldown.
    - last_seen_at         TIMESTAMP nullable
        Timestamp of the most recent suppressed duplicate (updated in-place).
    - escalated_from_alert_id  UUID nullable, FK -> alerts.id
        Set on the new alert when it was created as an escalation of a prior alert
        for the same contract (e.g., a LOW/MEDIUM that was superseded by a HIGH).
    - suppression_reason   VARCHAR(50) nullable
        "superseded" on an alert that has been replaced by an escalation.
        Null on active canonical alerts.
    - cooldown_expires_at  TIMESTAMP nullable
        When the cooldown window for this alert expires. New same-key alerts
        arriving before this timestamp are suppressed (duplicate_count++).
        Null = alert has never entered or has exited cooldown.

  tenant_signal_settings:
    - cooldown_window_minutes  INTEGER nullable
        Per-tenant cooldown override (minutes). Null = use global default.

  tenant_symbol_settings:
    - cooldown_window_minutes  INTEGER nullable
        Per-symbol cooldown override (highest priority). Null = inherit from tenant/global.

Revision: 008
Previous: 007_intelligence_layer
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- alerts ----
    op.add_column("alerts", sa.Column("dedupe_key", sa.String(255), nullable=True))
    op.add_column("alerts", sa.Column("duplicate_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("alerts", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "alerts",
        sa.Column(
            "escalated_from_alert_id",
            UUID(as_uuid=True),
            sa.ForeignKey("alerts.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column("alerts", sa.Column("suppression_reason", sa.String(50), nullable=True))
    op.add_column("alerts", sa.Column("cooldown_expires_at", sa.DateTime(timezone=True), nullable=True))

    # Index for fast cooldown lookups: given (tenant_id, dedupe_key), find the
    # active alert whose cooldown has not yet expired.
    op.create_index(
        "ix_alerts_dedupe_key",
        "alerts",
        ["tenant_id", "dedupe_key"],
        postgresql_where=sa.text("status = 'active'"),
    )

    # ---- tenant_signal_settings ----
    op.add_column(
        "tenant_signal_settings",
        sa.Column("cooldown_window_minutes", sa.Integer(), nullable=True),
    )

    # ---- tenant_symbol_settings ----
    op.add_column(
        "tenant_symbol_settings",
        sa.Column("cooldown_window_minutes", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tenant_symbol_settings", "cooldown_window_minutes")
    op.drop_column("tenant_signal_settings", "cooldown_window_minutes")
    op.drop_index("ix_alerts_dedupe_key", table_name="alerts")
    op.drop_column("alerts", "cooldown_expires_at")
    op.drop_column("alerts", "suppression_reason")
    op.drop_column("alerts", "escalated_from_alert_id")
    op.drop_column("alerts", "last_seen_at")
    op.drop_column("alerts", "duplicate_count")
    op.drop_column("alerts", "dedupe_key")
