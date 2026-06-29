"""Add the ``events`` table (Phase 3 — catalyst detector).

Typed, ticker-linked market catalysts extracted from news/filings, with a
materiality score and a unique ``dedup_key`` so extraction is idempotent.

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-29
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("materiality", sa.Float(), nullable=False, server_default="0"),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dedup_key", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("dedup_key", name="uq_events_dedup_key"),
    )
    op.create_index("ix_events_ticker", "events", ["ticker"])
    op.create_index("ix_events_kind", "events", ["kind"])
    op.create_index("ix_events_occurred_at", "events", ["occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_events_occurred_at", table_name="events")
    op.drop_index("ix_events_kind", table_name="events")
    op.drop_index("ix_events_ticker", table_name="events")
    op.drop_table("events")
