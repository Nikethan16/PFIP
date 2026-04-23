"""ML tables — backtest runs, calibration reports, model events, regime transitions.

Adds tables used by the ML/analytics backbone:
- ``backtest_runs``      — walk-forward backtest results (Sharpe, DD, etc.)
- ``calibration_reports`` — monthly Brier / ECE / reliability per model
- ``model_events``       — suspensions, reinstatements, retrainings
- ``regime_transitions`` — HMM regime changes per symbol

Revision ID: 0003
Revises: 0001
Create Date: 2026-04-21
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- backtest_runs ---
    op.create_table(
        "backtest_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("market", sa.String(), nullable=False),
        sa.Column("strategy", sa.String(), nullable=False),
        sa.Column("model_name", sa.String(), nullable=True),
        sa.Column("model_version", sa.String(), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column(
            "metrics",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "params",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("lookahead_ok", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_backtest_runs_market", "backtest_runs", ["market"])
    op.create_index("ix_backtest_runs_strategy", "backtest_runs", ["strategy"])
    op.create_index("ix_backtest_runs_created_at", "backtest_runs", ["created_at"])

    # --- calibration_reports (richer than the legacy ``calibration`` table) ---
    op.create_table(
        "calibration_reports",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("model_name", sa.String(), nullable=False),
        sa.Column("model_version", sa.String(), nullable=False),
        sa.Column("market", sa.String(), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("brier", sa.Float(), nullable=False),
        sa.Column("ece", sa.Float(), nullable=False),
        sa.Column("sharpness", sa.Float(), nullable=False),
        sa.Column("n_samples", sa.Integer(), nullable=False),
        sa.Column(
            "reliability",
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
    )
    op.create_index(
        "ix_calibration_reports_model", "calibration_reports", ["model_name", "model_version"]
    )
    op.create_index("ix_calibration_reports_market", "calibration_reports", ["market"])
    op.create_index("ix_calibration_reports_period_end", "calibration_reports", ["period_end"])

    # --- model_events (suspension / reinstatement / retraining) ---
    op.create_table(
        "model_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("model_name", sa.String(), nullable=False),
        sa.Column("model_version", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column(
            "at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_model_events_model", "model_events", ["model_name", "model_version"])
    op.create_index("ix_model_events_at", "model_events", ["at"])

    # --- regime_transitions (the regime table stores current labels; this is the
    #     dated log of transitions, used by regime_router for hysteresis).
    op.create_table(
        "regime_transitions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("from_regime", sa.String(), nullable=True),
        sa.Column("to_regime", sa.String(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_regime_transitions_symbol", "regime_transitions", ["symbol"])
    op.create_index("ix_regime_transitions_at", "regime_transitions", ["at"])


def downgrade() -> None:
    op.drop_index("ix_regime_transitions_at", table_name="regime_transitions")
    op.drop_index("ix_regime_transitions_symbol", table_name="regime_transitions")
    op.drop_table("regime_transitions")

    op.drop_index("ix_model_events_at", table_name="model_events")
    op.drop_index("ix_model_events_model", table_name="model_events")
    op.drop_table("model_events")

    op.drop_index("ix_calibration_reports_period_end", table_name="calibration_reports")
    op.drop_index("ix_calibration_reports_market", table_name="calibration_reports")
    op.drop_index("ix_calibration_reports_model", table_name="calibration_reports")
    op.drop_table("calibration_reports")

    op.drop_index("ix_backtest_runs_created_at", table_name="backtest_runs")
    op.drop_index("ix_backtest_runs_strategy", table_name="backtest_runs")
    op.drop_index("ix_backtest_runs_market", table_name="backtest_runs")
    op.drop_table("backtest_runs")
