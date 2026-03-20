"""
005 — Signal observability: per-run signal summaries + alert quality fields.

Adds:
  ingestion_runs.signal_summary_json   — full signal engine breakdown stored per run
  signal_features.raw_anomaly_score    — unpenalized score (before quality confidence)
  signal_features.quality_confidence  — penalty multiplier applied (0.5–1.0)
  alerts.raw_anomaly_score             — denormalised from feature for fast retrieval
  alerts.quality_confidence            — denormalised quality multiplier
  alerts.quality_flags                 — JSON-encoded list of quality flag strings
  alerts.dte_at_alert                  — days to expiry at alert creation time
"""

from alembic import op
import sqlalchemy as sa

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- ingestion_runs ----
    op.add_column(
        "ingestion_runs",
        sa.Column("signal_summary_json", sa.JSON(), nullable=True),
    )

    # ---- signal_features ----
    op.add_column(
        "signal_features",
        sa.Column("raw_anomaly_score", sa.Float(), nullable=True),
    )
    op.add_column(
        "signal_features",
        sa.Column("quality_confidence", sa.Float(), nullable=True),
    )

    # ---- alerts ----
    op.add_column(
        "alerts",
        sa.Column("raw_anomaly_score", sa.Float(), nullable=True),
    )
    op.add_column(
        "alerts",
        sa.Column("quality_confidence", sa.Float(), nullable=True),
    )
    op.add_column(
        "alerts",
        sa.Column("quality_flags", sa.Text(), nullable=True),
    )
    op.add_column(
        "alerts",
        sa.Column("dte_at_alert", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("alerts", "dte_at_alert")
    op.drop_column("alerts", "quality_flags")
    op.drop_column("alerts", "quality_confidence")
    op.drop_column("alerts", "raw_anomaly_score")
    op.drop_column("signal_features", "quality_confidence")
    op.drop_column("signal_features", "raw_anomaly_score")
    op.drop_column("ingestion_runs", "signal_summary_json")
