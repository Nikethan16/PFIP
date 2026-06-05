"""Watchlist delisting columns for survivorship-bias-aware universes.

Adds:
- ``watchlist.is_delisted`` (boolean, default false) — true once the
  symbol stops trading and the data feed dries up.
- ``watchlist.delisted_at`` (timestamp, nullable) — the day the symbol
  was confirmed delisted. Backtests filter on this.

Rows are retained — not soft-deleted — so any backtest with `as_of <
delisted_at` still includes the symbol. This is the only safe fix for
survivorship bias when the universe is small enough that drop-on-delist
materially affects results.

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-29
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "watchlist",
        sa.Column(
            "is_delisted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "watchlist",
        sa.Column(
            "delisted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    # Index lets us scan the universe quickly at a target date.
    op.create_index(
        "ix_watchlist_delisted_at",
        "watchlist",
        ["delisted_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_watchlist_delisted_at", table_name="watchlist")
    op.drop_column("watchlist", "delisted_at")
    op.drop_column("watchlist", "is_delisted")
