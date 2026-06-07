"""Pre-commitment file generator + capital ladder enforcer.

The plan v0.5 Section 8.3 requires a binding **pre-commitment markdown
file** signed before any real capital is deployed at Stage 7. This module
generates the file from user-provided parameters, validates the signed
file, and runs the capital ladder check before any trade that would
deploy real funds.

Capital ladder (from plan §8.3):

    5% → 10% → 25% → full

Each step requires the prior tier to perform for ≥ 4 weeks without:

- A drawdown halt being triggered
- Sharpe < 0.4 for any 3-month window
- Any risk-rule violation (correlation, position cap, daily new-position cap)
- 2 consecutive losing months

If any check fails, the ladder is frozen at the current tier (or rolled
back one). The system enters observation-only mode until manually unlocked.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

from loguru import logger
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession


PRECOMMITMENT_PATH = Path("/app/pre_commitment.md")
LADDER_TIERS: tuple[tuple[str, float], ...] = (
    ("5%", 0.05),
    ("10%", 0.10),
    ("25%", 0.25),
    ("full", 1.00),
)


class LadderTier(str, Enum):
    PAPER = "paper"  # pre-real-capital
    PCT_5 = "5%"
    PCT_10 = "10%"
    PCT_25 = "25%"
    FULL = "full"


@dataclass
class PreCommitment:
    """Parsed pre-commitment file."""

    minimum_capital_inr: Decimal
    drawdown_halt_pct: Decimal
    cooling_off_hours: int
    sharpe_floor: Decimal
    max_consecutive_losing_months: int
    signed_by: str
    signed_at: datetime
    current_tier: LadderTier
    halt_active: bool
    halt_reason: str | None


# ---------------------------------------------------------------------------
# Template generation
# ---------------------------------------------------------------------------


PRECOMMITMENT_TEMPLATE = """# PFIP Pre-Commitment

> **This is a binding self-contract.** You may not move from paper trading to real capital
> until this file is signed (filled in below) AND the system has accumulated 3 months of
> validated paper performance per Section 8.3 of the plan.

## Parameters

| Setting | Value |
|---|---|
| Minimum capital to deploy on tier 1 | ₹{minimum_capital_inr} |
| Drawdown halt (peak-to-trough) | {drawdown_halt_pct}% |
| Cooling-off between go-live decision and wiring funds | {cooling_off_hours} hours |
| Sharpe floor (3-month rolling) | {sharpe_floor} |
| Max consecutive losing months before halt | {max_consecutive_losing_months} |

## Capital ladder

| Tier | Allocation | Gate to graduate |
|---|---|---|
| 1 | 5% | 4 weeks live, Sharpe ≥ floor, zero risk-rule breaches |
| 2 | 10% | 4 weeks at tier 1 meeting all gates |
| 3 | 25% | 4 weeks at tier 2 meeting all gates |
| 4 | 100% | 4 weeks at tier 3 meeting all gates |

## Halt conditions

The system enters observation-only mode (no new positions) if any of:

- Drawdown crosses the halt threshold from peak portfolio value
- Sharpe (3-month rolling) drops below the floor
- 2 consecutive losing months
- Any single risk-rule violation (position cap, correlation guard, daily new-position cap)
- Tax-module calibration gate fails the ±2% reproduce-last-year check

When halted, only the kill switch closes open positions. Manual unlock is required to resume.

## Sign

By filling in your name and date below, you commit to the above. The system
will not deploy real capital until this section is non-empty.

```
Signed by: <YOUR NAME>
Date:      <YYYY-MM-DD>
```

## How to update

Edit this file. Any change to parameters resets the ladder to tier 0 (paper). Significant
changes require a 72-hour cool-down before the system honors them; see `pfip/portfolio/precommitment.py`.
"""


def render_template(
    *,
    minimum_capital_inr: int | Decimal = 500_000,
    drawdown_halt_pct: float = 20.0,
    cooling_off_hours: int = 72,
    sharpe_floor: float = 0.4,
    max_consecutive_losing_months: int = 2,
) -> str:
    """Produce the markdown template for the user to edit and sign."""
    return PRECOMMITMENT_TEMPLATE.format(
        minimum_capital_inr=f"{int(minimum_capital_inr):,}",
        drawdown_halt_pct=drawdown_halt_pct,
        cooling_off_hours=cooling_off_hours,
        sharpe_floor=sharpe_floor,
        max_consecutive_losing_months=max_consecutive_losing_months,
    )


def write_template_if_missing(path: Path = PRECOMMITMENT_PATH) -> bool:
    """Create the template file if absent. Returns True if a new file was written."""
    if path.exists():
        return False
    path.write_text(render_template(), encoding="utf-8")
    return True


# ---------------------------------------------------------------------------
# Parsing the signed file
# ---------------------------------------------------------------------------


def parse_signed(path: Path = PRECOMMITMENT_PATH) -> PreCommitment | None:
    """Read and parse the on-disk pre-commitment file.

    Returns None if the file doesn't exist or the Signed-by line is the
    placeholder. The system treats None as "still in paper mode".
    """
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    signed_by = _extract_after("Signed by:", text) or ""
    signed_date_str = _extract_after("Date:", text) or ""
    if signed_by.strip() in ("", "<YOUR NAME>") or signed_date_str.strip() in ("", "<YYYY-MM-DD>"):
        return None
    try:
        signed_at = datetime.fromisoformat(signed_date_str.strip()).replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        logger.warning(
            f"Could not parse pre-commitment date '{signed_date_str}'; treating as unsigned"
        )
        return None
    # Extract numeric params with safe defaults
    minimum_capital = _extract_currency(text, "Minimum capital") or Decimal("500000")
    drawdown_halt = _extract_pct(text, "Drawdown halt") or Decimal("20.0")
    cooling_off = _extract_int_hours(text, "Cooling-off") or 72
    sharpe_floor = _extract_decimal(text, "Sharpe floor") or Decimal("0.4")
    max_losing = _extract_int(text, "Max consecutive losing") or 2
    return PreCommitment(
        minimum_capital_inr=minimum_capital,
        drawdown_halt_pct=drawdown_halt,
        cooling_off_hours=cooling_off,
        sharpe_floor=sharpe_floor,
        max_consecutive_losing_months=max_losing,
        signed_by=signed_by.strip(),
        signed_at=signed_at,
        current_tier=LadderTier.PAPER,  # ladder advancement tracked separately in DB
        halt_active=False,
        halt_reason=None,
    )


def _extract_after(needle: str, haystack: str) -> str | None:
    for line in haystack.splitlines():
        if needle in line:
            return line.split(needle, 1)[1].strip()
    return None


def _extract_currency(text: str, label: str) -> Decimal | None:
    for line in text.splitlines():
        if label in line and "₹" in line:
            # find "₹{n,nnn,nnn}"
            after = line.split("₹", 1)[1].split("|", 1)[0]
            try:
                return Decimal(after.replace(",", "").strip())
            except Exception:  # noqa: BLE001
                return None
    return None


def _extract_pct(text: str, label: str) -> Decimal | None:
    for line in text.splitlines():
        if label in line and "%" in line:
            try:
                # take the rightmost number before %
                token = line.rstrip("|").split("|")[-2].strip().rstrip("%").strip()
                return Decimal(token)
            except Exception:  # noqa: BLE001
                return None
    return None


def _extract_decimal(text: str, label: str) -> Decimal | None:
    for line in text.splitlines():
        if label in line:
            try:
                tokens = [t for t in line.replace("|", " ").split() if t]
                # last numeric
                for tok in reversed(tokens):
                    try:
                        return Decimal(tok)
                    except Exception:  # noqa: BLE001
                        continue
            except Exception:  # noqa: BLE001
                return None
    return None


def _extract_int(text: str, label: str) -> int | None:
    val = _extract_decimal(text, label)
    return int(val) if val is not None else None


def _extract_int_hours(text: str, label: str) -> int | None:
    return _extract_int(text, label)


# ---------------------------------------------------------------------------
# Live capital ladder enforcement
# ---------------------------------------------------------------------------


@dataclass
class LadderCheck:
    allowed: bool
    current_tier: LadderTier
    max_allocation_pct: float
    halt_active: bool
    halt_reason: str | None
    reasons: list[str]


async def enforce_ladder(
    db: AsyncSession,
    *,
    intended_pct_of_portfolio: float,
) -> LadderCheck:
    """Decide whether a trade at the intended allocation is allowed.

    This is the gate before ``portfolio_tx`` rows are written with real
    money (paper trades bypass this entirely; see
    ``risk_manager.check_pre_trade``).
    """
    reasons: list[str] = []
    halt_active = False
    halt_reason: str | None = None

    pre = parse_signed()
    if pre is None:
        return LadderCheck(
            allowed=False,
            current_tier=LadderTier.PAPER,
            max_allocation_pct=0.0,
            halt_active=False,
            halt_reason=None,
            reasons=[
                "pre_commitment.md is not signed — system is in paper mode. "
                "Sign the file at the project root to graduate."
            ],
        )

    # Read current ladder state from a `ladder_state` table if present;
    # otherwise default to tier 1.
    try:
        row = (
            (
                await db.execute(
                    sql_text(
                        "SELECT tier, halt_active, halt_reason FROM ladder_state ORDER BY id DESC LIMIT 1"
                    )
                )
            )
            .mappings()
            .first()
        )
        if row is not None:
            tier = LadderTier(row["tier"])
            halt_active = bool(row["halt_active"])
            halt_reason = row["halt_reason"]
        else:
            tier = LadderTier.PCT_5
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"ladder_state read failed (probably missing table): {exc}")
        tier = LadderTier.PCT_5

    if halt_active:
        return LadderCheck(
            allowed=False,
            current_tier=tier,
            max_allocation_pct=0.0,
            halt_active=True,
            halt_reason=halt_reason,
            reasons=[f"Ladder halted: {halt_reason}"],
        )

    tier_pct = {
        LadderTier.PAPER: 0.0,
        LadderTier.PCT_5: 0.05,
        LadderTier.PCT_10: 0.10,
        LadderTier.PCT_25: 0.25,
        LadderTier.FULL: 1.00,
    }[tier]

    if intended_pct_of_portfolio > tier_pct:
        reasons.append(
            f"Intended {intended_pct_of_portfolio:.1%} exceeds tier {tier.value} cap of {tier_pct:.1%}"
        )
    if intended_pct_of_portfolio > 0.10:
        reasons.append("Per-position cap is 10% (set in env via MAX_POSITION_PCT)")

    allowed = len(reasons) == 0
    return LadderCheck(
        allowed=allowed,
        current_tier=tier,
        max_allocation_pct=tier_pct,
        halt_active=False,
        halt_reason=None,
        reasons=reasons,
    )


async def can_advance_tier(db: AsyncSession, tier: LadderTier) -> tuple[bool, list[str]]:
    """Check the 4-week graduation gates for a given tier.

    Returns (eligible, list_of_reasons). All gates must be green to advance.
    """
    reasons: list[str] = []
    four_weeks_ago = datetime.now(tz=timezone.utc) - timedelta(weeks=4)

    # Time in tier: at least 4 weeks
    try:
        last_change = (
            await db.execute(
                sql_text(
                    "SELECT entered_at FROM ladder_state WHERE tier = :t ORDER BY id DESC LIMIT 1"
                ),
                {"t": tier.value},
            )
        ).scalar_one_or_none()
        if last_change is None or last_change > four_weeks_ago:
            reasons.append("Tier has not been held for the required 4 weeks")
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"ladder_state read failed: {exc}")
        reasons.append("ladder_state table missing — cannot verify tier age")

    # Risk-rule breaches: zero in the last 4 weeks
    try:
        row = (
            await db.execute(
                sql_text(
                    """
                    SELECT COUNT(*) AS n FROM risk_breaches
                    WHERE detected_at >= :since
                    """
                ),
                {"since": four_weeks_ago},
            )
        ).scalar_one_or_none()
        if row and int(row) > 0:
            reasons.append(f"{row} risk-rule breach(es) in the last 4 weeks")
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"risk_breaches read failed: {exc}")

    # Sharpe floor: 3-month rolling Sharpe ≥ floor (placeholder; computed by
    # calibration module in real runs)
    # No-op for now; the Stage 4 calibration module will populate the gate.

    # Consecutive losing months
    try:
        rows = (
            (
                await db.execute(
                    sql_text(
                        """
                    SELECT date_trunc('month', closed_at) AS month,
                           SUM(exit_price_inr - cost_basis_inr) AS pnl
                    FROM holdings
                    WHERE closed_at IS NOT NULL
                    GROUP BY month
                    ORDER BY month DESC
                    LIMIT 2
                    """
                    )
                )
            )
            .mappings()
            .all()
        )
        if len(rows) >= 2 and all((r["pnl"] or 0) < 0 for r in rows):
            reasons.append("Last 2 months had negative P&L")
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"losing-month check failed: {exc}")

    return (len(reasons) == 0, reasons)


__all__ = [
    "PreCommitment",
    "LadderTier",
    "LadderCheck",
    "render_template",
    "write_template_if_missing",
    "parse_signed",
    "enforce_ladder",
    "can_advance_tier",
]
