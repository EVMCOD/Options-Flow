"""009 — Event catalyst model and alert enrichment fields

Revision ID: 009
Revises: 008
Create Date: 2026-03-20

Changes
-------
1. New table `symbol_events` — stores upcoming event catalysts per symbol.
   Scoped per tenant or global (tenant_id IS NULL).

2. Four new nullable columns on `alerts` — snapshot of the nearest upcoming
   event at the time the alert was created.  Stored denormalised so the alert
   record is self-contained even if the event is later edited or deleted.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. symbol_events table ────────────────────────────────────────────────
    op.create_table(
        "symbol_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("event_time", sa.String(10), nullable=True),
        sa.Column("source", sa.String(100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    op.create_index(
        "ix_symbol_events_symbol_date",
        "symbol_events",
        ["symbol", "event_date"],
    )
    op.create_index(
        "ix_symbol_events_tenant_symbol_date",
        "symbol_events",
        ["tenant_id", "symbol", "event_date"],
    )

    # ── 2. Catalyst context columns on alerts ─────────────────────────────────
    op.add_column("alerts", sa.Column("catalyst_context", sa.String(100), nullable=True))
    op.add_column("alerts", sa.Column("days_to_event", sa.Integer(), nullable=True))
    op.add_column("alerts", sa.Column("next_event_type", sa.String(50), nullable=True))
    op.add_column("alerts", sa.Column("next_event_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("alerts", "next_event_date")
    op.drop_column("alerts", "next_event_type")
    op.drop_column("alerts", "days_to_event")
    op.drop_column("alerts", "catalyst_context")

    op.drop_index("ix_symbol_events_tenant_symbol_date", table_name="symbol_events")
    op.drop_index("ix_symbol_events_symbol_date", table_name="symbol_events")
    op.drop_table("symbol_events")
