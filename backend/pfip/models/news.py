"""News table."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Float, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from pfip.db.base import Base


class NewsRow(Base):
    """A news / social item.

    ``category`` distinguishes regular news from regulatory/corporate items:
    ``news`` (default) | ``sec_filing`` (US filings) | ``corp_announcement``
    (India) | ``earnings_calendar`` | ``academic`` | insider/PIT disclosures.
    The enrichment columns (``embedded``, ``impact_score``, ``entity_tickers``)
    were added by migration ``0005`` and ``category`` by an earlier migration;
    they are mapped here so ORM reads (e.g. the diligence aggregator) see them.
    All have DB-side defaults so existing inserts that omit them still work.
    """

    __tablename__ = "news"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    source: Mapped[str] = mapped_column(String, nullable=False)
    symbol: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    sentiment: Mapped[float | None] = mapped_column(Float, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(
        String, nullable=False, server_default="news", default="news", index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    embedded: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", default=False
    )
    impact_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    entity_tickers: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default="[]", default=list
    )
