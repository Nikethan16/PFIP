"""Ingest layer additions — source_health, mf_nav, fx_rates, macro_series.

Adds:
- ``source_health`` — per-adapter run ledger (last success time + row counts + last error).
- ``mf_nav`` — AMFI mutual fund NAV table (separate from ohlcv to keep the
  hypertable focused on tradeable instruments).
- ``fx_rates`` — daily FX reference rates (separate from ohlcv for the same
  reason; one row per (date, base, quote, source)).
- ``macro_series`` — long-form macro time series (FRED/DBnomics/World Bank).

All tables are idempotent / upsert-safe.

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-29
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # source_health — per-adapter run ledger
    # ------------------------------------------------------------------
    op.create_table(
        "source_health",
        sa.Column("source", sa.String(), nullable=False),
        sa.Column(
            "last_run_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_rows", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "consecutive_failures",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("source"),
    )
    op.create_index("ix_source_health_last_run_at", "source_health", [sa.text("last_run_at DESC")])

    # ------------------------------------------------------------------
    # mf_nav — AMFI daily NAVs
    # ------------------------------------------------------------------
    op.create_table(
        "mf_nav",
        sa.Column("nav_date", sa.Date(), nullable=False),
        sa.Column("scheme_code", sa.String(), nullable=False),
        sa.Column("scheme_name", sa.Text(), nullable=True),
        sa.Column("isin_payout", sa.String(), nullable=True),
        sa.Column("isin_reinvest", sa.String(), nullable=True),
        sa.Column("nav", sa.Numeric(20, 6), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("nav_date", "scheme_code"),
    )
    op.create_index("ix_mf_nav_scheme_code", "mf_nav", ["scheme_code"])

    # ------------------------------------------------------------------
    # fx_rates — daily FX reference rates
    # ------------------------------------------------------------------
    op.create_table(
        "fx_rates",
        sa.Column("rate_date", sa.Date(), nullable=False),
        sa.Column("base", sa.String(8), nullable=False),
        sa.Column("quote", sa.String(8), nullable=False),
        sa.Column("rate", sa.Numeric(20, 8), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("rate_date", "base", "quote", "source"),
    )
    op.create_index(
        "ix_fx_rates_base_quote_date", "fx_rates", ["base", "quote", sa.text("rate_date DESC")]
    )

    # ------------------------------------------------------------------
    # macro_series — long-form macro time series
    # ------------------------------------------------------------------
    op.create_table(
        "macro_series",
        sa.Column("series_id", sa.String(), nullable=False),
        sa.Column("obs_date", sa.Date(), nullable=False),
        sa.Column("value", sa.Numeric(30, 10), nullable=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("frequency", sa.String(), nullable=True),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("series_id", "obs_date", "source"),
    )
    op.create_index(
        "ix_macro_series_id_date", "macro_series", ["series_id", sa.text("obs_date DESC")]
    )


def downgrade() -> None:
    op.drop_index("ix_macro_series_id_date", table_name="macro_series")
    op.drop_table("macro_series")
    op.drop_index("ix_fx_rates_base_quote_date", table_name="fx_rates")
    op.drop_table("fx_rates")
    op.drop_index("ix_mf_nav_scheme_code", table_name="mf_nav")
    op.drop_table("mf_nav")
    op.drop_index("ix_source_health_last_run_at", table_name="source_health")
    op.drop_table("source_health")
