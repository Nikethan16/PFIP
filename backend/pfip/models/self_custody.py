"""Self-custody wallet address ledger.

Mirrors the ``self_custody_addresses`` table created in Alembic migration 0002.
Each row is one on-chain address the user wants tracked. The hourly /6h Prefect
flows read ``(chain, address)`` from this table and call the matching adapter
(``mempool_btc`` / ``etherscan`` / ``solscan``), writing the latest balance into
the ``fundamentals`` table keyed by ``symbol = address``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from pfip.db.base import Base


class SelfCustodyAddressRow(Base):
    """One self-custody on-chain address owned by a user."""

    __tablename__ = "self_custody_addresses"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    chain: Mapped[str] = mapped_column(String, nullable=False)  # btc, eth, sol
    address: Mapped[str] = mapped_column(String, nullable=False)
    label: Mapped[str | None] = mapped_column(String, nullable=True)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("user_id", "chain", "address", name="uq_self_custody_user_chain_addr"),
    )
