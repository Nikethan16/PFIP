"""OHLCV table — TimescaleDB hypertable, partitioned by ``time``."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, PrimaryKeyConstraint, String
from sqlalchemy.orm import Mapped, mapped_column, synonym

from pfip.db.base import Base


class OHLCVRow(Base):
    """A single OHLCV bar. Primary key: (time, symbol, source, timeframe)."""

    __tablename__ = "ohlcv"

    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Back-compat alias: many call sites reference ``OHLCVRow.ts``. A synonym
    # maps it to the real ``time`` column for projection, filtering, ordering.
    ts = synonym("time")
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    market: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    timeframe: Mapped[str] = mapped_column(String, nullable=False)

    open: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    volume: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("time", "symbol", "source", "timeframe", name="pk_ohlcv"),
    )
