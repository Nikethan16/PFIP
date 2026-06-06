"""Single-row user settings table.

PFIP is single-user (see ``deps.get_current_user_email`` — one operator), so
this table holds at most one row. Risk/tax/alert/UI preferences live in a JSONB
``prefs`` blob keyed by the frontend ``UserSettings`` field names; the typed
risk columns are duplicated out so the ``RiskManager`` / signal pipeline can
read them without parsing JSON. The router seeds the row from
``core.config.Settings`` defaults on first GET.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from pfip.db.base import Base


class UserSettingsRow(Base):
    """The single user-settings row. All editable preferences live in ``prefs``."""

    __tablename__ = "user_settings"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # The whole settings payload (frontend UserSettings shape) as a JSON blob.
    # Keeping it a single column means new preference fields never need a
    # migration — the API merges defaults over whatever is stored.
    prefs: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
