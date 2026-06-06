"""Add the single-row ``user_settings`` table.

Backs ``GET/PATCH /api/v1/settings`` — risk limits, tax year, alert
preferences, model-registry defaults, scheduled-task flags. PFIP is
single-user so the table holds at most one row; all editable preferences live
in a JSONB ``prefs`` blob so new fields never require a follow-up migration.

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-06
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_settings",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("prefs", JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("user_settings")
