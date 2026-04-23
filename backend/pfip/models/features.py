"""Computed feature rows.

Features are derived from OHLCV + fundamentals; one row per
(symbol, source, timeframe, time). We store a canonical set + a JSONB blob of
extras for forward-compat.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, PrimaryKeyConstraint, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pfip.db.base import Base


class FeatureRow(Base):
    """A computed feature snapshot."""

    __tablename__ = "features"

    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    timeframe: Mapped[str] = mapped_column(String, nullable=False)

    rsi_14: Mapped[float | None] = mapped_column(Float, nullable=True)
    macd: Mapped[float | None] = mapped_column(Float, nullable=True)
    macd_signal: Mapped[float | None] = mapped_column(Float, nullable=True)
    macd_hist: Mapped[float | None] = mapped_column(Float, nullable=True)
    atr_14: Mapped[float | None] = mapped_column(Float, nullable=True)
    return_7d: Mapped[float | None] = mapped_column(Float, nullable=True)
    volatility_30d: Mapped[float | None] = mapped_column(Float, nullable=True)

    extras: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        PrimaryKeyConstraint("time", "symbol", "source", "timeframe", name="pk_features"),
    )
