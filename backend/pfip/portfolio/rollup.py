"""Materialize ``holdings`` from the ``portfolio_tx`` ledger.

Broker-CSV imports (``POST /portfolio/import``) land as ``portfolio_tx`` rows
with ``holding_id = None`` — the ledger is the source of truth but nothing rolls
those events up into the ``holdings`` book, so the Portfolio / dashboard views
stay empty after a "successful" import. This module closes that gap.

What it does
------------
:func:`rebuild_holdings_from_tx` groups the ledger by
``(symbol, category, broker, is_self_custody)`` and, for each group, computes:

* **net qty** = Σ BUY qty − Σ SELL qty
* **weighted-average cost basis** over BUY legs only — total BUY ``amount_inr``
  divided by total BUY qty. (Average cost, *not* FIFO. This matches the existing
  :meth:`PortfolioService.weighted_avg_cost_basis` / :meth:`compute_pnl`
  semantics so PnL stays internally consistent; it is also the simplest defensible
  basis for an Indian-resident book where the tax engine recomputes lots
  separately.)

It then UPSERTs one ``holdings`` row per still-open group. The operation is
**idempotent**: re-running fully recomputes from the ledger and overwrites the
materialized rows it owns, so an import can call it repeatedly without
double-counting.

Symbol / asset-class recovery
-----------------------------
The import endpoint does not persist a symbol column (``portfolio_tx`` has none).
Instead it stamps a structured prefix into ``note``::

    [<broker>:<symbol>] <free text> [asset_class=<class>]

:func:`parse_tx_note` recovers ``broker``, ``symbol`` and ``asset_class`` from
that prefix. Rows whose symbol can't be recovered (manual / legacy rows already
tied to a holding, or cash/transfer noise) are skipped — this service only
materializes *import-originated, holding-less* rows, leaving manually managed
holdings untouched.

Ownership marker
----------------
Rows this service creates carry ``HoldingRow.notes`` starting with
``_ROLLUP_MARKER`` so a recompute can find and replace exactly the rows it owns
without clobbering manually-added holdings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from pfip.core.contracts import Holding, HoldingCategory
from pfip.models.holdings import HoldingRow
from pfip.models.portfolio_tx import PortfolioTxRow

# Holdings materialized from the ledger carry this marker in ``notes`` so a
# recompute replaces exactly its own rows (and never a manual holding).
_ROLLUP_MARKER = "[rollup]"

# ``[broker:symbol]`` prefix the import endpoint writes, e.g. ``[zerodha:TCS.NS]``.
_NOTE_PREFIX_RE = re.compile(r"^\[([^:\]]+):([^\]]+)\]")
# Optional ``[asset_class=...]`` tag (written by the tax-focused parse path).
_ASSET_CLASS_RE = re.compile(r"\[asset_class=([a-z_]+)\]")

# Broker → asset-class hint, mirroring ``csv_adapters.router`` so the import and
# the rollup agree even when no explicit ``[asset_class=...]`` tag is present.
_VDA_BROKERS = {"wazirx", "coindcx", "binance", "coinbase", "kraken"}
_US_BROKERS = {"indmoney", "vested"}

# asset_class string → HoldingCategory for the materialized holding.
# NOTE: the import path only ever emits ``equity`` / ``us_stock`` / ``vda``
# (see ``csv_adapters.router.tax_focused_parse``); the extra rows make the map
# total against ``HarvestAssetClass`` without inventing enum members. There is no
# US-specific or plain-gold holding category, so US stocks fold into EQUITY and
# gold into SGB (sovereign gold) as the nearest real bucket.
_ASSET_CLASS_TO_CATEGORY: dict[str, HoldingCategory] = {
    "vda": HoldingCategory.CRYPTO_EXCHANGE,
    "crypto": HoldingCategory.CRYPTO_EXCHANGE,
    "us_stock": HoldingCategory.EQUITY,
    "equity": HoldingCategory.EQUITY,
    "equity_mf": HoldingCategory.MUTUAL_FUND,
    "debt_mf": HoldingCategory.MUTUAL_FUND,
    "gold": HoldingCategory.SGB,
}

_QTY_KINDS = {"BUY", "SELL"}


def encode_tx_note(*, broker: str, symbol: str, asset_class: str, free: str | None = None) -> str:
    """Build the ``note`` the import endpoint stores so rollup can recover it.

    Shape: ``[<broker>:<symbol>] <free> [asset_class=<class>]``.
    """
    head = f"[{broker}:{symbol}]"
    mid = f" {free.strip()}" if free and free.strip() else ""
    tail = f" [asset_class={asset_class}]"
    return f"{head}{mid}{tail}".strip()


@dataclass(slots=True)
class TxNote:
    """Structured fields recovered from a ``portfolio_tx.note``."""

    broker: str | None
    symbol: str | None
    asset_class: str | None


def parse_tx_note(note: str | None) -> TxNote:
    """Recover ``(broker, symbol, asset_class)`` from a ledger note prefix."""
    if not note:
        return TxNote(None, None, None)
    broker = symbol = None
    m = _NOTE_PREFIX_RE.match(note)
    if m:
        broker = m.group(1).strip() or None
        symbol = m.group(2).strip() or None
    ac_m = _ASSET_CLASS_RE.search(note)
    asset_class = ac_m.group(1) if ac_m else None
    return TxNote(broker=broker, symbol=symbol, asset_class=asset_class)


def asset_class_for(broker: str | None, explicit: str | None) -> str:
    """Resolve the asset class for a row: explicit tag wins, else broker hint."""
    if explicit:
        return explicit
    b = (broker or "").lower()
    if b in _VDA_BROKERS:
        return "vda"
    if b in _US_BROKERS:
        return "us_stock"
    return "equity"


def category_for(asset_class: str) -> HoldingCategory:
    """Map a resolved asset class to a ``HoldingCategory`` for the holding."""
    return _ASSET_CLASS_TO_CATEGORY.get(asset_class, HoldingCategory.EQUITY)


@dataclass(slots=True)
class _Group:
    """Running aggregation for one (symbol, category, broker, self_custody) key."""

    symbol: str
    category: HoldingCategory
    broker: str | None
    is_self_custody: bool
    asset_class: str
    buy_qty: Decimal = Decimal("0")
    buy_amount: Decimal = Decimal("0")
    sell_qty: Decimal = Decimal("0")
    sell_amount: Decimal = Decimal("0")
    first_buy_at: datetime | None = None
    last_sell_at: datetime | None = None
    last_sell_price: Decimal | None = None
    isin: str | None = None
    fx_rate: Decimal | None = None
    cost_basis_ccy: str = "INR"

    @property
    def net_qty(self) -> Decimal:
        return (self.buy_qty - self.sell_qty).quantize(Decimal("0.00000001"))

    @property
    def avg_cost_per_unit(self) -> Decimal:
        if self.buy_qty <= 0:
            return Decimal("0")
        return (self.buy_amount / self.buy_qty).quantize(Decimal("0.0001"))


# Imports are exchange tradebooks → never self-custody. (Self-custody wallets are
# tracked via the dedicated /self-custody router + on-chain balances, not the
# tradebook ledger.)
_IMPORT_IS_SELF_CUSTODY = False


async def rebuild_holdings_from_tx(
    session: Any,
    *,
    asset_class: str | None = None,
) -> list[Holding]:
    """Recompute ``holdings`` from import-originated ``portfolio_tx`` rows.

    Args:
        session: an ``AsyncSession`` (or compatible) — committed at the end.
        asset_class: optional filter; when given, only ledger rows resolving to
            this asset class are rolled up (e.g. ``"vda"`` to rebuild only the
            crypto book). ``None`` rebuilds everything.

    Returns:
        The list of materialized open holdings as ``contracts.Holding`` models.

    Behaviour:
        * Groups by ``(symbol, category, broker, is_self_custody)``.
        * Net qty = ΣBUY − ΣSELL; weighted-average cost basis over BUY legs.
        * Idempotent: deletes the rollup-owned holdings (and only those) for the
          targeted asset class, then re-inserts the still-open groups. A group
          whose net qty rounds to ≤ 0 is treated as fully closed and is *not*
          re-materialized (the realized history stays in the ledger).
    """
    stmt = select(PortfolioTxRow).order_by(PortfolioTxRow.time.asc())
    res = await session.execute(stmt)
    rows = list(res.scalars().all())

    groups: dict[tuple[str, str, str, bool], _Group] = {}

    for tx in rows:
        # Only roll up import-originated, holding-less rows. Manual holdings keep
        # their own ledger linkage and are managed via the holdings CRUD.
        if tx.holding_id is not None:
            continue
        parsed = parse_tx_note(tx.note)
        if not parsed.symbol:
            continue  # cash/transfer noise or legacy row with no symbol prefix
        symbol = parsed.symbol
        if symbol.upper() == "CASH":
            continue
        ac = asset_class_for(parsed.broker, parsed.asset_class)
        if asset_class is not None and ac != asset_class:
            continue
        cat = category_for(ac)
        self_cust = _IMPORT_IS_SELF_CUSTODY

        key = (symbol, cat.value, parsed.broker or "", self_cust)
        g = groups.get(key)
        if g is None:
            g = _Group(
                symbol=symbol,
                category=cat,
                broker=parsed.broker,
                is_self_custody=self_cust,
                asset_class=ac,
            )
            groups[key] = g

        kind = (tx.kind or "").upper()
        if kind not in _QTY_KINDS:
            continue  # dividends/fees/tds/transfers don't move the position
        qty = Decimal(str(tx.qty or 0))
        amt = Decimal(str(tx.amount_inr or 0))
        if tx.fx_rate is not None and g.fx_rate is None:
            g.fx_rate = Decimal(str(tx.fx_rate))
        if kind == "BUY":
            g.buy_qty += qty
            g.buy_amount += amt
            if g.first_buy_at is None or tx.time < g.first_buy_at:
                g.first_buy_at = tx.time
        else:  # SELL
            g.sell_qty += qty
            g.sell_amount += amt
            if g.last_sell_at is None or tx.time > g.last_sell_at:
                g.last_sell_at = tx.time
                if qty > 0:
                    g.last_sell_price = (amt / qty).quantize(Decimal("0.0001"))

    # --- Replace the rollup-owned holdings idempotently. ---
    # Delete existing rollup rows for the targeted classes only.
    del_stmt = select(HoldingRow).where(HoldingRow.notes.like(f"{_ROLLUP_MARKER}%"))
    existing = (await session.execute(del_stmt)).scalars().all()
    target_categories = {category_for(asset_class).value} if asset_class is not None else None
    for row in existing:
        if target_categories is None or row.category in target_categories:
            await session.delete(row)

    materialized: list[HoldingRow] = []
    now = datetime.now(tz=timezone.utc)
    for g in groups.values():
        net = g.net_qty
        if net <= Decimal("0"):
            # Fully (or over-) closed: don't re-materialize an open holding.
            continue
        # Average-cost basis of the *remaining* units = avg_cost_per_unit * net.
        cost_basis_inr = (g.avg_cost_per_unit * net).quantize(Decimal("0.01"))
        note = (
            f"{_ROLLUP_MARKER} {g.broker or 'import'}:{g.symbol} "
            f"net={net} avg_cost={g.avg_cost_per_unit} (materialized {now.date().isoformat()})"
        )
        row = HoldingRow(
            category=g.category.value,
            symbol=g.symbol,
            isin=g.isin,
            broker=g.broker,
            account_id=None,
            acquired_at=g.first_buy_at or now,
            qty=net,
            cost_basis_inr=cost_basis_inr,
            cost_basis_ccy=g.cost_basis_ccy,
            fx_rate=g.fx_rate,
            is_self_custody=g.is_self_custody,
            notes=note,
            closed_at=None,
            exit_price_inr=None,
        )
        session.add(row)
        materialized.append(row)

    await session.commit()
    for row in materialized:
        await session.refresh(row)

    return [Holding.model_validate(r) for r in materialized]
