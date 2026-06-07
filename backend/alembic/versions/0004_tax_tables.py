"""Tax tables — cg_events, tax_snapshots, dividend_events, form_67_rows, schedule_fa_rows.

Adds:
- ``cg_events`` — classified capital-gains events (one row per sell-fill leg).
- ``tax_snapshots`` — FY-level cached computations.
- ``dividend_events`` — dividend ledger with TDS.
- ``form_67_rows`` — DTAA Section 90 credit rows.
- ``schedule_fa_rows`` — Schedule FA foreign-asset rows.

Revision ID: 0004
Revises: 0002
Create Date: 2026-04-21
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- cg_events ---
    op.create_table(
        "cg_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("fy", sa.String(), nullable=False),  # e.g. "2026-27"
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("asset_class", sa.String(), nullable=False),
        sa.Column("term", sa.String(), nullable=False),  # STCG / LTCG
        sa.Column("qty", sa.Numeric(), nullable=False),
        sa.Column("buy_date", sa.Date(), nullable=False),
        sa.Column("sell_date", sa.Date(), nullable=False),
        sa.Column("buy_cost_inr", sa.Numeric(), nullable=False),
        sa.Column("sell_proceeds_inr", sa.Numeric(), nullable=False),
        sa.Column("gain_inr", sa.Numeric(), nullable=False),
        sa.Column(
            "grandfathered",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("tds_inr", sa.Numeric(), nullable=False, server_default=sa.text("0")),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cg_events_fy", "cg_events", ["fy"])
    op.create_index("ix_cg_events_symbol", "cg_events", ["symbol"])
    op.create_index("ix_cg_events_fy_asset_class", "cg_events", ["fy", "asset_class"])

    # --- tax_snapshots ---
    op.create_table(
        "tax_snapshots",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("fy", sa.String(), nullable=False),
        sa.Column("stcg_equity_inr", sa.Numeric(), nullable=False),
        sa.Column("ltcg_equity_inr", sa.Numeric(), nullable=False),
        sa.Column("vda_gain_inr", sa.Numeric(), nullable=False),
        sa.Column("vda_tds_inr", sa.Numeric(), nullable=False),
        sa.Column("dividend_inr", sa.Numeric(), nullable=False),
        sa.Column("interest_inr", sa.Numeric(), nullable=False),
        sa.Column("total_tax_inr", sa.Numeric(), nullable=False),
        sa.Column("recommended_regime", sa.String(), nullable=False),
        sa.Column("recommended_itr", sa.String(), nullable=False),
        sa.Column(
            "surcharge_warnings",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fy", name="uq_tax_snapshots_fy"),
    )

    # --- dividend_events ---
    op.create_table(
        "dividend_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("holding_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("paid_on", sa.Date(), nullable=False),
        sa.Column("amount_inr", sa.Numeric(), nullable=False),
        sa.Column("amount_ccy", sa.String(), nullable=False, server_default="INR"),
        sa.Column("amount_native", sa.Numeric(), nullable=True),
        sa.Column("fx_rate", sa.Numeric(), nullable=True),
        sa.Column(
            "tax_withheld_inr",
            sa.Numeric(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("source_country", sa.String(), nullable=False, server_default="IN"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["holding_id"], ["holdings.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dividend_events_symbol", "dividend_events", ["symbol"])
    op.create_index("ix_dividend_events_paid_on", "dividend_events", ["paid_on"])

    # --- form_67_rows ---
    op.create_table(
        "form_67_rows",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("fy", sa.String(), nullable=False),
        sa.Column("country", sa.String(), nullable=False, server_default="USA"),
        sa.Column("source_name", sa.String(), nullable=False),
        sa.Column("foreign_income_inr", sa.Numeric(), nullable=False),
        sa.Column("tax_paid_abroad_inr", sa.Numeric(), nullable=False),
        sa.Column("indian_tax_on_same_income_inr", sa.Numeric(), nullable=False),
        sa.Column("dtaa_credit_inr", sa.Numeric(), nullable=False),
        sa.Column("section", sa.String(), nullable=False, server_default="90"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_form_67_rows_fy", "form_67_rows", ["fy"])

    # --- schedule_fa_rows ---
    op.create_table(
        "schedule_fa_rows",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("fy", sa.String(), nullable=False),
        sa.Column("country", sa.String(), nullable=False, server_default="USA"),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("isin", sa.String(), nullable=True),
        sa.Column("acquired_on", sa.Date(), nullable=True),
        sa.Column("peak_balance_usd", sa.Numeric(), nullable=False),
        sa.Column("peak_balance_inr", sa.Numeric(), nullable=False),
        sa.Column("closing_balance_usd", sa.Numeric(), nullable=False),
        sa.Column("closing_balance_inr", sa.Numeric(), nullable=False),
        sa.Column(
            "gross_interest_usd",
            sa.Numeric(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "gross_dividend_usd",
            sa.Numeric(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "gross_proceeds_usd",
            sa.Numeric(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_schedule_fa_rows_fy", "schedule_fa_rows", ["fy"])
    op.create_index("ix_schedule_fa_rows_symbol", "schedule_fa_rows", ["symbol"])


def downgrade() -> None:
    op.drop_index("ix_schedule_fa_rows_symbol", table_name="schedule_fa_rows")
    op.drop_index("ix_schedule_fa_rows_fy", table_name="schedule_fa_rows")
    op.drop_table("schedule_fa_rows")
    op.drop_index("ix_form_67_rows_fy", table_name="form_67_rows")
    op.drop_table("form_67_rows")
    op.drop_index("ix_dividend_events_paid_on", table_name="dividend_events")
    op.drop_index("ix_dividend_events_symbol", table_name="dividend_events")
    op.drop_table("dividend_events")
    op.drop_table("tax_snapshots")
    op.drop_index("ix_cg_events_fy_asset_class", table_name="cg_events")
    op.drop_index("ix_cg_events_symbol", table_name="cg_events")
    op.drop_index("ix_cg_events_fy", table_name="cg_events")
    op.drop_table("cg_events")
