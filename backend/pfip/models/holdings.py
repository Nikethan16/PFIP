"""Holdings table — every owned instrument across categories."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from pfip.db.base import Base


class HoldingRow(Base):
    """A holding. Soft-closed via ``closed_at`` rather than deleted."""

    __tablename__ = "holdings"

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
