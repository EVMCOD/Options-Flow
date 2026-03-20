"""007_intelligence_layer

Add fields required by the intelligence product layer (v1):

  alerts:
    - priority_score            FLOAT nullable
        Intrinsic priority 0–10. Combines anomaly_score, premium_proxy,
        quality_confidence, and per-symbol priority_weight.
        Computed by the signal engine at alert creation.
        At query time the ranking endpoint applies an additional recency
        decay on top to produce a live ranked score.
    - contributing_factors_json JSON nullable
        Machine-readable breakdown of the signals that triggered this alert.
        Schema: { volume_spike, notional, timing, quality, moneyness }.

  tenant_symbol_settings:
    - priority_weight  FLOAT nullable (default 1.0 when null)
        Per-client symbol importance multiplier.
        Range: 0.0–3.0. 0 = deprioritised; 2+ = featured/core.
        Flows into priority_score via EffectiveSignalSettings.
    - watchlist_tier   VARCHAR(20) nullable
        Optional client-facing categorisation: "core" | "secondary".
        Displayed in the UI and can be used to filter/sort alert lists.

Revision: 007
Previous: 006_signal_settings
"""

from alembic import op
import sqlalchemy as sa

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- alerts ----
    op.add_column("alerts", sa.Column("priority_score", sa.Float(), nullable=True))
    op.add_column("alerts", sa.Column("contributing_factors_json", sa.JSON(), nullable=True))

    # ---- tenant_symbol_settings ----
    op.add_column(
        "tenant_symbol_settings",
        sa.Column("priority_weight", sa.Float(), nullable=True),
    )
    op.add_column(
        "tenant_symbol_settings",
        sa.Column("watchlist_tier", sa.String(20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tenant_symbol_settings", "watchlist_tier")
    op.drop_column("tenant_symbol_settings", "priority_weight")
    op.drop_column("alerts", "contributing_factors_json")
    op.drop_column("alerts", "priority_score")
