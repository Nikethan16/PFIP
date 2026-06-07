"""Initial schema — every table from CONTRACTS.md plus features.

TimescaleDB hypertables are created on ``ohlcv`` and ``fundamentals``. The
migration is idempotent for hypertable creation (``if_not_exists => TRUE``).

Revision ID: 0001
Revises:
Create Date: 2026-04-21
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Extensions (TimescaleDB + pgcrypto for gen_random_uuid) ---
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # --- ohlcv ---
    op.create_table(
        "ohlcv",
        sa.Column("time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("market", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("timeframe", sa.String(), nullable=False),
        sa.Column("open", sa.Numeric(20, 8), nullable=False),
        sa.Column("high", sa.Numeric(20, 8), nullable=False),
        sa.Column("low", sa.Numeric(20, 8), nullable=False),
        sa.Column("close", sa.Numeric(20, 8), nullable=False),
        sa.Column("volume", sa.Numeric(30, 8), nullable=False),
        sa.PrimaryKeyConstraint("time", "symbol", "source", "timeframe", name="pk_ohlcv"),
    )
    op.execute(
        "SELECT create_hypertable('ohlcv', 'time', if_not_exists => TRUE, migrate_data => TRUE)"
    )
    op.create_index("ix_ohlcv_symbol_time", "ohlcv", ["symbol", "time"])

    # --- fundamentals ---
    op.create_table(
        "fundamentals",
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("field", sa.String(), nullable=False),
        sa.Column("value", sa.Numeric(), nullable=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("as_of_date", "symbol", "field", "source", name="pk_fundamentals"),
    )
    # Hypertable on as_of_date (fundamentals are PIT by discovery date).
    op.execute(
        "SELECT create_hypertable('fundamentals', 'as_of_date', "
        "if_not_exists => TRUE, migrate_data => TRUE)"
    )
    op.create_index("ix_fundamentals_symbol_field", "fundamentals", ["symbol", "field"])

    # --- features ---
    op.create_table(
        "features",
        sa.Column("time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("timeframe", sa.String(), nullable=False),
        sa.Column("rsi_14", sa.Float(), nullable=True),
        sa.Column("macd", sa.Float(), nullable=True),
        sa.Column("macd_signal", sa.Float(), nullable=True),
        sa.Column("macd_hist", sa.Float(), nullable=True),
        sa.Column("atr_14", sa.Float(), nullable=True),
        sa.Column("return_7d", sa.Float(), nullable=True),
        sa.Column("volatility_30d", sa.Float(), nullable=True),
        sa.Column(
            "extras",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.PrimaryKeyConstraint("time", "symbol", "source", "timeframe", name="pk_features"),
    )
    op.create_index("ix_features_symbol_time", "features", ["symbol", "time"])

    # --- holdings ---
    op.create_table(
        "holdings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=True),
        sa.Column("isin", sa.String(), nullable=True),
        sa.Column("broker", sa.String(), nullable=True),
        sa.Column("account_id", sa.String(), nullable=True),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("qty", sa.Numeric(), nullable=False),
        sa.Column("cost_basis_inr", sa.Numeric(), nullable=False),
        sa.Column("cost_basis_ccy", sa.String(), nullable=False, server_default="INR"),
        sa.Column("fx_rate", sa.Numeric(), nullable=True),
        sa.Column(
            "is_self_custody",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exit_price_inr", sa.Numeric(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    # --- portfolio_tx ---
    op.create_table(
        "portfolio_tx",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("holding_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("qty", sa.Numeric(), nullable=True),
        sa.Column("price", sa.Numeric(), nullable=True),
        sa.Column("amount_inr", sa.Numeric(), nullable=False),
        sa.Column("fx_rate", sa.Numeric(), nullable=True),
        sa.Column("tax_withheld", sa.Numeric(), nullable=False, server_default=sa.text("0")),
        sa.Column("note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["holding_id"], ["holdings.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_portfolio_tx_time", "portfolio_tx", ["time"])

    # --- shadow_holdings ---
    op.create_table(
        "shadow_holdings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=True),
        sa.Column("isin", sa.String(), nullable=True),
        sa.Column("broker", sa.String(), nullable=True),
        sa.Column("account_id", sa.String(), nullable=True),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("qty", sa.Numeric(), nullable=False),
        sa.Column("cost_basis_inr", sa.Numeric(), nullable=False),
        sa.Column("cost_basis_ccy", sa.String(), nullable=False, server_default="INR"),
        sa.Column("fx_rate", sa.Numeric(), nullable=True),
        sa.Column(
            "is_self_custody",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exit_price_inr", sa.Numeric(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    # --- shadow_portfolio_tx ---
    op.create_table(
        "shadow_portfolio_tx",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("holding_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("qty", sa.Numeric(), nullable=True),
        sa.Column("price", sa.Numeric(), nullable=True),
        sa.Column("amount_inr", sa.Numeric(), nullable=False),
        sa.Column("fx_rate", sa.Numeric(), nullable=True),
        sa.Column("tax_withheld", sa.Numeric(), nullable=False, server_default=sa.text("0")),
        sa.Column("note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["holding_id"], ["shadow_holdings.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # --- watchlist ---
    op.create_table(
        "watchlist",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("market", sa.String(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol", "market", name="uq_watchlist_symbol_market"),
    )

    # --- signals ---
    op.create_table(
        "signals",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("asset", sa.String(), nullable=False),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=False),
        sa.Column("horizon_hours", sa.Integer(), nullable=False),
        sa.Column("regime", sa.String(), nullable=False),
        sa.Column("model_name", sa.String(), nullable=False),
        sa.Column("model_version", sa.String(), nullable=False),
        sa.Column(
            "drivers",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "counter_arguments",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_signals_asset", "signals", ["asset"])
    op.create_index("ix_signals_generated_at", "signals", ["generated_at"])

    # --- news ---
    op.create_table(
        "news",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=True),
        sa.Column("sentiment", sa.Float(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("url", name="uq_news_url"),
    )
    op.create_index("ix_news_time", "news", ["time"])
    op.create_index("ix_news_symbol", "news", ["symbol"])

    # --- regime ---
    op.create_table(
        "regime",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("regime", sa.String(), nullable=False),
        sa.Column("since", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_regime_symbol", "regime", ["symbol"])

    # --- calibration ---
    op.create_table(
        "calibration",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("model_name", sa.String(), nullable=False),
        sa.Column("model_version", sa.String(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("brier_score", sa.Float(), nullable=False),
        sa.Column("ece", sa.Float(), nullable=False),
        sa.Column("reliability", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("n_samples", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_calibration_model_name", "calibration", ["model_name"])

    # --- journal ---
    op.create_table(
        "journal",
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
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("thesis", sa.Text(), nullable=False),
        sa.Column(
            "pre_trade_checklist",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("post_mortem", sa.Text(), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_journal_symbol", "journal", ["symbol"])


def downgrade() -> None:
    op.drop_index("ix_journal_symbol", table_name="journal")
    op.drop_table("journal")
    op.drop_index("ix_calibration_model_name", table_name="calibration")
    op.drop_table("calibration")
    op.drop_index("ix_regime_symbol", table_name="regime")
    op.drop_table("regime")
    op.drop_index("ix_news_symbol", table_name="news")
    op.drop_index("ix_news_time", table_name="news")
    op.drop_table("news")
    op.drop_index("ix_signals_generated_at", table_name="signals")
    op.drop_index("ix_signals_asset", table_name="signals")
    op.drop_table("signals")
    op.drop_table("watchlist")
    op.drop_table("shadow_portfolio_tx")
    op.drop_table("shadow_holdings")
    op.drop_index("ix_portfolio_tx_time", table_name="portfolio_tx")
    op.drop_table("portfolio_tx")
    op.drop_table("holdings")
    op.drop_index("ix_features_symbol_time", table_name="features")
    op.drop_table("features")
    op.drop_index("ix_fundamentals_symbol_field", table_name="fundamentals")
    op.drop_table("fundamentals")
    op.drop_index("ix_ohlcv_symbol_time", table_name="ohlcv")
    op.drop_table("ohlcv")
