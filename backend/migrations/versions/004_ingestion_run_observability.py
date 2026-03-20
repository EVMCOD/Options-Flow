"""Ingestion run observability: add market_data_mode

Adds market_data_mode (varchar 20, nullable) to ingestion_runs.
Values: "delayed" | "live" | "mock" — stamped from provider.market_data_mode()
at run creation time. Allows filtering run history by data freshness without
joining through provider configs.

Revision ID: 004
Revises: 003
Create Date: 2025-01-04 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ingestion_runs",
        sa.Column("market_data_mode", sa.String(20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ingestion_runs", "market_data_mode")
