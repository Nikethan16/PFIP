"""Canonical Pydantic models matching `docs/CONTRACTS.md`.

The frontend mirrors these as TypeScript in `/frontend/lib/contracts.ts`. Any
change here must propagate. Unknown fields are rejected by design.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Market(str, Enum):
    """Supported markets / underlyings.

    Note: we allow arbitrary strings for Indian equities (e.g. ``RELIANCE.NS``)
    elsewhere; this enum lists only the named roll-ups.
    """

    BTC_USD = "BTC_USD"
    ETH_USD = "ETH_USD"
    SOL_USD = "SOL_USD"
    BNB_USD = "BNB_USD"

    SPY = "SPY"
    QQQ = "QQQ"
    DIA = "DIA"
    VTI = "VTI"

    NIFTY50 = "NIFTY50"
    NIFTY500 = "NIFTY500"
    SENSEX = "SENSEX"

    USDINR = "USDINR"
    EURUSD = "EURUSD"
    GBPUSD = "GBPUSD"


class Source(str, Enum):
    """Data source identifiers."""

    COINBASE = "coinbase"
    KRAKEN = "kraken"
    BYBIT = "bybit"
    OKX = "okx"
    YFINANCE = "yfinance"
    STOOQ = "stooq"
    JUGAAD = "jugaad"
    AMFI = "amfi"
    FRANKFURTER = "frankfurter"
    RBI = "rbi"
    FRED = "fred"
    SEC_EDGAR = "sec_edgar"


class Regime(str, Enum):
    """Market regime label."""

    BULL_TREND = "bull_trend"
    BEAR_TREND = "bear_trend"
    SIDEWAYS = "sideways"
    HIGH_VOLATILITY = "high_volatility"
    ACCUMULATION = "accumulation"
    DISTRIBUTION = "distribution"


class HoldingCategory(str, Enum):
    """Portfolio holding categories."""

    EQUITY = "equity"
    ETF = "etf"
    MUTUAL_FUND = "mutual_fund"
    PPF = "ppf"
    EPF = "epf"
    NPS = "nps"
    FD = "fd"
    SGB = "sgb"
    GSEC = "gsec"
    BOND = "bond"
    CRYPTO_EXCHANGE = "crypto_exchange"
    CRYPTO_SELF_CUSTODY = "crypto_self_custody"
    CASH = "cash"


class SignalDirection(str, Enum):
    """Signal direction."""

    BUY = "BUY"
    HOLD = "HOLD"
    SELL = "SELL"


class Timeframe(str, Enum):
    """OHLCV timeframes."""

    M1 = "1m"
    M5 = "5m"
    H1 = "1h"
    D1 = "1d"


class PortfolioTxKind(str, Enum):
    """Ledger transaction kinds."""

    BUY = "BUY"
    SELL = "SELL"
    DIVIDEND = "DIVIDEND"
    INTEREST = "INTEREST"
    TRANSFER = "TRANSFER"
    FEE = "FEE"
    TDS = "TDS"


# ---------------------------------------------------------------------------
# Base model config (strict, forbid unknowns)
# ---------------------------------------------------------------------------


class _StrictBase(BaseModel):
    """Base Pydantic model — strict, forbid extras."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        from_attributes=True,
    )


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------


class Driver(_StrictBase):
    """SHAP-style driver for a signal."""

    feature: str
    contribution: float


class Signal(_StrictBase):
    """The typed signal contract — the seam between M4 (ML) and M7 (agent)."""

    direction: SignalDirection
    confidence: int = Field(ge=0, le=100)
    horizon_hours: int = Field(ge=1)
    drivers: list[Driver] = Field(default_factory=list, max_length=5)
    counter_arguments: list[Driver] = Field(default_factory=list, max_length=3)
    regime: Regime
    model_name: str
    model_version: str
    asset: str
    generated_at: datetime


# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------


class OHLCV(_StrictBase):
    """An OHLCV row as returned by the API."""

    time: datetime
    symbol: str
    market: str
    source: Source
    timeframe: Timeframe
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


class Fundamental(_StrictBase):
    """A fundamentals row (point-in-time)."""

    as_of_date: date
    report_date: date
    symbol: str
    field: str
    value: Decimal | None = None
    source: Source


# ---------------------------------------------------------------------------
# Portfolio
# ---------------------------------------------------------------------------


class Holding(_StrictBase):
    """A current or historical holding."""

    id: UUID | None = None
    category: HoldingCategory
    symbol: str | None = None
    isin: str | None = None
    broker: str | None = None
    account_id: str | None = None
    acquired_at: datetime
    qty: Decimal
    cost_basis_inr: Decimal
    cost_basis_ccy: str = "INR"
    fx_rate: Decimal | None = None
    is_self_custody: bool = False
    notes: str | None = None
    closed_at: datetime | None = None
    exit_price_inr: Decimal | None = None


class PortfolioTx(_StrictBase):
    """A ledger transaction."""

    id: UUID | None = None
    holding_id: UUID | None = None
    time: datetime
    kind: PortfolioTxKind
    qty: Decimal | None = None
    price: Decimal | None = None
    amount_inr: Decimal
    fx_rate: Decimal | None = None
    tax_withheld: Decimal = Decimal("0")
    note: str | None = None


class PortfolioSummary(_StrictBase):
    """Response shape for ``GET /portfolio/summary``."""

    total_inr: Decimal
    pnl_inr: Decimal
    pnl_pct: float
    exposure_by_category: dict[str, Decimal]
    drawdown: float


# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------


class WatchlistItem(_StrictBase):
    """A watchlist row."""

    id: UUID | None = None
    symbol: str
    market: str
    note: str | None = None
    added_at: datetime | None = None


class WatchlistCreate(_StrictBase):
    """Request body for ``POST /watchlist``."""

    symbol: str
    market: str
    note: str | None = None


# ---------------------------------------------------------------------------
# News
# ---------------------------------------------------------------------------


class NewsItem(_StrictBase):
    """A news item surfaced to the user."""

    id: UUID | None = None
    time: datetime
    title: str
    url: str
    source: str
    symbol: str | None = None
    sentiment: float | None = Field(default=None, ge=-1.0, le=1.0)
    summary: str | None = None


# ---------------------------------------------------------------------------
# Regime
# ---------------------------------------------------------------------------


class RegimeLabel(_StrictBase):
    """Regime classification output for an asset at a point in time."""

    symbol: str
    regime: Regime
    since: datetime
    confidence: float = Field(ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------


class CalibrationReport(_StrictBase):
    """Per-model calibration snapshot."""

    model_name: str
    model_version: str
    as_of: datetime
    brier_score: float
    ece: float  # expected calibration error
    reliability: list[tuple[float, float]]  # [(predicted_bucket, observed_freq), ...]
    n_samples: int


# ---------------------------------------------------------------------------
# Journal
# ---------------------------------------------------------------------------


class JournalEntryCreate(_StrictBase):
    """Request body for ``POST /journal/entries``. Checklist is required."""

    symbol: str
    direction: SignalDirection
    thesis: str
    pre_trade_checklist: dict[str, bool]  # e.g. {"regime_check": True, ...}
    notes: str | None = None


class JournalEntry(_StrictBase):
    """A journal row."""

    id: UUID | None = None
    created_at: datetime
    symbol: str
    direction: SignalDirection
    thesis: str
    pre_trade_checklist: dict[str, bool]
    post_mortem: str | None = None
    closed_at: datetime | None = None
    notes: str | None = None


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class LoginRequest(_StrictBase):
    """``POST /auth/login`` body."""

    email: str
    password: str


class TokenResponse(_StrictBase):
    """Auth token + expiry."""

    token: str
    expiresAt: datetime  # noqa: N815  — contract field


class CurrentUser(_StrictBase):
    """``GET /auth/me`` response."""

    email: str


# ---------------------------------------------------------------------------
# Error envelope (RFC 7807)
# ---------------------------------------------------------------------------


class ProblemDetail(_StrictBase):
    """RFC 7807 problem+json body."""

    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
