"""Shadow portfolio — mirror of holdings + portfolio_tx with separate tables."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from pfip.db.base import Base


class ShadowHoldingRow(Base):
    """Shadow (paper-trading) holding row."""

    __tablename__ = "shadow_holdings"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    category: Mapped[str] = mapped_column(String, nullable=False)
    symbol: Mapped[str | None] = mapped_column(String, nullable=True)
    isin: Mapped[str | None] = mapped_column(String, nullable=True)
    broker: Mapped[str | None] = mapped_column(String, nullable=True)
    account_id: Mapped[str | None] = mapped_column(String, nullable=True)
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    qty: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    cost_basis_inr: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    cost_basis_ccy: Mapped[str] = mapped_column(String, default="INR", nullable=False)
    fx_rate: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    is_self_custody: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_price_inr: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)


class ShadowPortfolioTxRow(Base):
    """Shadow (paper-trading) ledger transaction."""

    __tablename__ = "shadow_portfolio_tx"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    holding_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("shadow_holdings.id"), nullable=True
    )
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    qty: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    price: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    amount_inr: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    fx_rate: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    tax_withheld: Mapped[Decimal] = mapped_column(
        Numeric, default=Decimal("0"), nullable=False
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
