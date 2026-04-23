"""News sources, watchlist feeds, self-custody addresses, and news category.

Adds:
- ``news_sources`` registry table
- ``watchlist_news_feeds`` per-ticker feed mapping
- ``self_custody_addresses`` user-address ledger
- ``news.category`` column (default ``'news'``) and composite index
  ``(category, created_at DESC)`` for category-scoped news queries

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-21
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- news.category + created_at ---
    op.add_column(
        "news",
        sa.Column(
            "category",
            sa.String(),
            nullable=False,
            server_default="news",
        ),
    )
    op.add_column(
        "news",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_news_category_created_at",
        "news",
        ["category", sa.text("created_at DESC")],
    )

    # --- news_sources ---
    op.create_table(
        "news_sources",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),  # rss, api, scrape, social
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column(
            "active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("last_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", "url", name="uq_news_sources_name_url"),
    )
    op.create_index("ix_news_sources_active", "news_sources", ["active"])

    # --- watchlist_news_feeds ---
    op.create_table(
        "watchlist_news_feeds",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "watchlist_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("google_news_query", sa.Text(), nullable=True),
        sa.Column("yahoo_rss_url", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["watchlist_id"], ["watchlist.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "watchlist_id", name="uq_watchlist_news_feeds_watchlist"
        ),
    )

    # --- self_custody_addresses ---
    op.create_table(
        "self_custody_addresses",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("chain", sa.String(), nullable=False),  # btc, eth, sol
        sa.Column("address", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "chain", "address", name="uq_self_custody_user_chain_addr"
        ),
    )
    op.create_index(
        "ix_self_custody_user_chain", "self_custody_addresses", ["user_id", "chain"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_self_custody_user_chain", table_name="self_custody_addresses"
    )
    op.drop_table("self_custody_addresses")
    op.drop_table("watchlist_news_feeds")
    op.drop_index("ix_news_sources_active", table_name="news_sources")
    op.drop_table("news_sources")
    op.drop_index("ix_news_category_created_at", table_name="news")
    op.drop_column("news", "created_at")
    op.drop_column("news", "category")
