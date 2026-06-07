"""Fundamentals table — point-in-time aware."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Numeric, PrimaryKeyConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from pfip.db.base import Base


class FundamentalRow(Base):
    """A single fundamental observation.

    ``as_of_date`` is the date the value first became known to us (for PIT);
    ``report_date`` is the business period the value covers. Queries MUST
    filter ``as_of_date <= point_in_time_t``. Restatements are new rows.
    """

    __tablename__ = "fundamentals"

    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    field: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    source: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("as_of_date", "symbol", "field", "source", name="pk_fundamentals"),
    )
