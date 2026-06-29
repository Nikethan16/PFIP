"""Catalyst / corporate-event table (Phase 3).

Typed events extracted from ingested news + filings — earnings surprises,
contract/tender wins, rating changes, M&A, regulatory actions, buybacks,
guidance — linked to a ticker with a 0..1 materiality score. Drives the events
feed + catalyst alerts. ``dedup_key`` makes extraction idempotent across runs.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from pfip.db.base import Base


class EventRow(Base):
    """A discrete, ticker-linked market catalyst."""

    __tablename__ = "events"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    ticker: Mapped[str] = mapped_column(String, nullable=False, index=True)
    # earnings_surprise | contract_win | upgrade | downgrade | m_and_a |
    # regulatory | buyback | guidance | management | other
    kind: Mapped[str] = mapped_column(String, nullable=False, index=True)
    materiality: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    # Stable hash of (ticker, kind, headline-ish) so re-extraction upserts.
    dedup_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
