"""Self-custody wallet router — add / list / delete tracked on-chain addresses.

The ingest side already exists: hourly / 6h Prefect flows read
``self_custody_addresses`` and call the per-chain adapters (mempool / etherscan /
solscan), which write the latest balance into the ``fundamentals`` table keyed by
``symbol = address``. What was missing was any way to *manage* those addresses —
this router closes that gap.

Endpoints (all auth-gated; rows are scoped to the caller's email = ``user_id``):

* ``GET    /self-custody/wallets``            → list the user's wallets
* ``POST   /self-custody/wallets``            → add ``{chain, address, label?}``
* ``DELETE /self-custody/wallets/{id}``       → remove one wallet
* ``GET    /self-custody/wallets/balances``   → latest synced balance per wallet

Supported chains: ``btc`` / ``eth`` / ``sol`` (matching the adapter set). Each
add does light, offline format validation so obviously-bad addresses are
rejected before the ingest flow ever tries to use them.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select

from pfip.api.deps import CurrentUser, DbSession
from pfip.models.fundamentals import FundamentalRow
from pfip.models.self_custody import SelfCustodyAddressRow

router = APIRouter(prefix="/self-custody", tags=["self-custody"])


# ---------------------------------------------------------------------------
# Chain config + light address validation
# ---------------------------------------------------------------------------

SUPPORTED_CHAINS = ("btc", "eth", "sol")

# The ``fundamentals.field`` each adapter writes the spendable balance under,
# plus the on-chain base unit and a divisor to a human-readable amount.
_BALANCE_FIELD: dict[str, str] = {
    "btc": "btc_balance_sat",
    "eth": "eth_balance",
    "sol": "sol_lamports",
}
_BALANCE_UNIT: dict[str, str] = {
    "btc": "sat",
    "eth": "eth",  # adapter already converts wei → ETH
    "sol": "lamports",
}
# Divisor to convert the stored value into a whole-coin amount for the UI.
_TO_WHOLE: dict[str, int] = {
    "btc": 100_000_000,  # sat → BTC
    "eth": 1,  # already ETH
    "sol": 1_000_000_000,  # lamports → SOL
}

# Address shape checks — deliberately permissive (format, not checksum):
#   BTC: base58 P2PKH/P2SH (1/3…) or bech32 (bc1…).
#   ETH: 0x + 40 hex.
#   SOL: base58, 32–44 chars (Ed25519 pubkey).
_BTC_BASE58 = re.compile(r"^[13][a-km-zA-HJ-NP-Z1-9]{25,39}$")
_BTC_BECH32 = re.compile(r"^bc1[a-z0-9]{11,71}$")
_ETH_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
_SOL_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


def _validate_address(chain: str, address: str) -> None:
    """Raise ``ValueError`` if ``address`` doesn't look valid for ``chain``."""
    addr = address.strip()
    if not addr:
        raise ValueError("address must not be empty")
    if chain == "btc":
        if not (_BTC_BASE58.match(addr) or _BTC_BECH32.match(addr.lower())):
            raise ValueError("not a valid BTC address (expected 1…/3…/bc1…)")
    elif chain == "eth":
        if not _ETH_RE.match(addr):
            raise ValueError("not a valid ETH address (expected 0x + 40 hex chars)")
    elif chain == "sol":
        if not _SOL_RE.match(addr):
            raise ValueError("not a valid SOL address (expected base58, 32–44 chars)")
    else:  # pragma: no cover — guarded by the model validator
        raise ValueError(f"unsupported chain {chain!r}")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class WalletCreate(BaseModel):
    """Body for ``POST /self-custody/wallets``."""

    chain: str
    address: str
    label: Optional[str] = None

    @field_validator("chain")
    @classmethod
    def _chain_supported(cls, v: str) -> str:
        c = v.strip().lower()
        if c not in SUPPORTED_CHAINS:
            raise ValueError(f"chain must be one of {', '.join(SUPPORTED_CHAINS)}")
        return c

    @field_validator("address")
    @classmethod
    def _strip_address(cls, v: str) -> str:
        return v.strip()


class WalletOut(BaseModel):
    """A self-custody wallet row."""

    id: UUID
    chain: str
    address: str
    label: Optional[str] = None
    added_at: datetime


class WalletBalanceOut(WalletOut):
    """A wallet plus its latest synced balance (or nulls if never synced)."""

    balance_raw: Optional[float] = None  # value as stored (sat / ETH / lamports)
    balance: Optional[float] = None  # whole-coin amount (BTC / ETH / SOL)
    unit: str
    as_of: Optional[str] = None  # ISO date of the latest fundamentals snapshot
    synced: bool = False


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/wallets", response_model=list[WalletOut])
async def list_wallets(db: DbSession, user: CurrentUser) -> list[WalletOut]:
    """List the caller's tracked self-custody wallets (newest first)."""
    stmt = (
        select(SelfCustodyAddressRow)
        .where(SelfCustodyAddressRow.user_id == user)
        .order_by(SelfCustodyAddressRow.added_at.desc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [
        WalletOut(
            id=r.id,
            chain=r.chain,
            address=r.address,
            label=r.label,
            added_at=r.added_at,
        )
        for r in rows
    ]


@router.post("/wallets", response_model=WalletOut, status_code=status.HTTP_201_CREATED)
async def add_wallet(body: WalletCreate, db: DbSession, user: CurrentUser) -> WalletOut:
    """Add a wallet. Validates the address format and rejects duplicates."""
    try:
        _validate_address(body.chain, body.address)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_address", "message": str(exc)},
        ) from exc

    # Duplicate guard (also enforced by the uq_user_chain_addr constraint).
    dup = (
        (
            await db.execute(
                select(SelfCustodyAddressRow).where(
                    SelfCustodyAddressRow.user_id == user,
                    SelfCustodyAddressRow.chain == body.chain,
                    SelfCustodyAddressRow.address == body.address,
                )
            )
        )
        .scalars()
        .first()
    )
    if dup is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This address is already tracked for this chain.",
        )

    row = SelfCustodyAddressRow(
        user_id=user,
        chain=body.chain,
        address=body.address,
        label=body.label,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return WalletOut(
        id=row.id,
        chain=row.chain,
        address=row.address,
        label=row.label,
        added_at=row.added_at,
    )


@router.delete("/wallets/{wallet_id}", status_code=status.HTTP_200_OK)
async def delete_wallet(wallet_id: UUID, db: DbSession, user: CurrentUser) -> dict:
    """Remove one of the caller's wallets. 404 if it isn't theirs."""
    row = (
        (
            await db.execute(
                select(SelfCustodyAddressRow).where(
                    SelfCustodyAddressRow.id == wallet_id,
                    SelfCustodyAddressRow.user_id == user,
                )
            )
        )
        .scalars()
        .first()
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Wallet not found")
    await db.delete(row)
    await db.commit()
    return {"deleted": str(wallet_id)}


@router.get("/wallets/balances", response_model=list[WalletBalanceOut])
async def wallet_balances(db: DbSession, user: CurrentUser) -> list[WalletBalanceOut]:
    """Latest synced balance per wallet.

    Joins each of the caller's wallets to the most recent ``fundamentals`` row
    (``symbol = address``, ``field = <chain balance field>``). Wallets the ingest
    flow hasn't synced yet come back with ``synced=False`` and null balances.
    """
    stmt = (
        select(SelfCustodyAddressRow)
        .where(SelfCustodyAddressRow.user_id == user)
        .order_by(SelfCustodyAddressRow.added_at.desc())
    )
    wallets = (await db.execute(stmt)).scalars().all()

    out: list[WalletBalanceOut] = []
    for w in wallets:
        field = _BALANCE_FIELD.get(w.chain)
        unit = _BALANCE_UNIT.get(w.chain, "")
        balance_raw: float | None = None
        as_of: str | None = None
        if field is not None:
            bal_stmt = (
                select(FundamentalRow.value, FundamentalRow.as_of_date)
                .where(
                    FundamentalRow.symbol == w.address,
                    FundamentalRow.field == field,
                )
                .order_by(FundamentalRow.as_of_date.desc())
                .limit(1)
            )
            res = (await db.execute(bal_stmt)).first()
            if res is not None and res[0] is not None:
                balance_raw = float(res[0])
                as_of = res[1].isoformat() if res[1] is not None else None

        balance_whole = balance_raw / _TO_WHOLE.get(w.chain, 1) if balance_raw is not None else None
        out.append(
            WalletBalanceOut(
                id=w.id,
                chain=w.chain,
                address=w.address,
                label=w.label,
                added_at=w.added_at,
                balance_raw=balance_raw,
                balance=balance_whole,
                unit=unit,
                as_of=as_of,
                synced=balance_raw is not None,
            )
        )
    return out
