"""KB + agent tables, news embedding/sentiment/impact columns, prompt-injection quarantine.

Adds:
- ``agent_sessions`` — chat-session persistence (per plan §12.1 / §7).
- ``kb_ingestions`` — knowledge-base ingest ledger (per plan §10).
- ``news`` additions: ``embedded BOOLEAN``, ``sentiment NUMERIC`` *(widened)*,
  ``impact_score NUMERIC``, ``entity_tickers JSONB``.
- ``model_events`` — quarantine + prompt-injection event log (plan §5.5).

Note: ``news.sentiment`` already exists as ``Float``; we add a
``news.impact_score`` column and an ``embedded`` flag plus JSON
``entity_tickers``. We also keep ``news.sentiment`` as-is.

Revision ID: 0005
Revises: 0002
Create Date: 2026-04-21
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # news additions: embedded flag, impact score, entity tickers
    # ------------------------------------------------------------------
    op.add_column(
        "news",
        sa.Column(
            "embedded",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "news",
        sa.Column(
            "impact_score",
            sa.Numeric(6, 4),
            nullable=True,
        ),
    )
    op.add_column(
        "news",
        sa.Column(
            "entity_tickers",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.create_index(
        "ix_news_embedded",
        "news",
        ["embedded"],
    )
    op.create_index(
        "ix_news_impact_score",
        "news",
        [sa.text("impact_score DESC")],
    )

    # ------------------------------------------------------------------
    # agent_sessions — conversation history per chat session
    # ------------------------------------------------------------------
    op.create_table(
        "agent_sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "messages",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_sessions_user_id_created",
        "agent_sessions",
        ["user_id", sa.text("created_at DESC")],
    )

    # ------------------------------------------------------------------
    # kb_ingestions — one row per book/source we've chunk-embedded
    # ------------------------------------------------------------------
    op.create_table(
        "kb_ingestions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("author", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("path_hash", sa.String(length=64), nullable=False),
        sa.Column("chunks_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "embedded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("path_hash", name="uq_kb_ingestions_path_hash"),
    )
    op.create_index("ix_kb_ingestions_title", "kb_ingestions", ["title"])

    # ------------------------------------------------------------------
    # model_events — prompt-injection quarantine + model-health events
    # ------------------------------------------------------------------
    op.create_table(
        "model_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("kind", sa.String(), nullable=False),  # e.g. 'prompt_injection', 'llm_timeout', 'hallucination'
        sa.Column("severity", sa.String(), nullable=False, server_default="warn"),
        sa.Column("source", sa.String(), nullable=True),  # origin URL / book title / session id
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("quarantined", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_model_events_kind_created", "model_events", ["kind", sa.text("created_at DESC")])


def downgrade() -> None:
    op.drop_index("ix_model_events_kind_created", table_name="model_events")
    op.drop_table("model_events")
    op.drop_index("ix_kb_ingestions_title", table_name="kb_ingestions")
    op.drop_table("kb_ingestions")
    op.drop_index("ix_agent_sessions_user_id_created", table_name="agent_sessions")
    op.drop_table("agent_sessions")
    op.drop_index("ix_news_impact_score", table_name="news")
    op.drop_index("ix_news_embedded", table_name="news")
    op.drop_column("news", "entity_tickers")
    op.drop_column("news", "impact_score")
    op.drop_column("news", "embedded")
