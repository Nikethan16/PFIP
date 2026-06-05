"""Add `last_batch_key` column to `source_health`.

Supports the idempotent-ingest layer (`pfip.ingest._common.idempotency`).
On retries the adapter checks this key against the precomputed batch
SHA; if equal, the insert is skipped.

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-29
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "source_health",
        sa.Column("last_batch_key", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("source_health", "last_batch_key")
