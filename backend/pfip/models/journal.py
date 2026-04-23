"""Trading journal — enforces pre-trade checklist presence."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from pfip.db.base import Base


class JournalRow(Base):
    """A journal entry capturing a trading thesis + pre-trade checklist.

    ``post_mortem`` and ``closed_at`` are filled when the entry is closed.
    """

    __tablename__ = "journal"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    symbol: Mapped[str] = mapped_column(String, nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String, nullable=False)
    thesis: Mapped[str] = mapped_column(Text, nullable=False)
    pre_trade_checklist: Mapped[dict[str, bool]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    post_mortem: Mapped[str | None] = mapped_column(Text, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
