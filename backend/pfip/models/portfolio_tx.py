"""Portfolio transaction ledger (double-entry-ish over holdings)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from pfip.db.base import Base


class PortfolioTxRow(Base):
    """One ledger event (BUY/SELL/DIVIDEND/INTEREST/FEE/TDS/TRANSFER)."""

    __tablename__ = "portfolio_tx"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    holding_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("holdings.id"), nullable=True
    )
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    qty: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    price: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    amount_inr: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    fx_rate: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    tax_withheld: Mapped[Decimal] = mapped_column(Numeric, default=Decimal("0"), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
