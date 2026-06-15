"""Render the Section 12.1 morning brief as Markdown.

Eight sections, all data-grounded. The LLM is only allowed to write the
one-line connective sentence at the top of each section; the numbers come
from DB queries and are passed through verbatim.

Sections:
1. Overnight moves — BTC/ETH/SOL %, SPX futures %, Nifty futures gap, USDINR.
2. Economic calendar today (HIGH impact only).
3. Top 3 overnight news per watchlist.
4. Regime state per market.
5. Watchlist deltas (biggest movers + unusual volume).
6. Open-position risk snapshot.
7. Calibration note (any model whose ECE breached last monthly run).
8. Shadow vs actual one-line delta.

The function returns a Markdown string. If the LLM is unavailable we still
return the brief — prose is replaced by ``_(LLM unavailable)_`` stubs but
the numerical sections remain accurate. This is intentional: the brief must
be reproducible from DB alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from loguru import logger
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from pfip.agent.llm_client import (
    ChatMessage,
    LLMAllProvidersFailed,
    LLMUnavailable,
    get_llm_client,
    get_llm_router,
)
from pfip.agent.prompts import load as load_prompt
from pfip.agent.router import Sensitivity, TaskType

# ---------------------------------------------------------------------------
# Data dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _PricePoint:
    symbol: str
    time: datetime
    close: Decimal
    prev_close: Decimal | None

    @property
    def pct_change(self) -> float | None:
        if self.prev_close is None or self.prev_close == 0:
            return None
        return float((self.close - self.prev_close) / self.prev_close) * 100.0


# ---------------------------------------------------------------------------
# DB helpers — each returns a small, JSON-ready structure
# ---------------------------------------------------------------------------


async def _latest_two(db: AsyncSession, symbol: str, timeframe: str = "1d") -> _PricePoint | None:
    try:
        stmt = sql_text("""
            SELECT time, close
            FROM ohlcv
            WHERE symbol = :symbol AND timeframe = :tf
            ORDER BY time DESC
            LIMIT 2
            """)
        rows = list((await db.execute(stmt, {"symbol": symbol, "tf": timeframe})).mappings())
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"latest_two({symbol}) failed: {exc}")
        return None
    if not rows:
        return None
    latest = rows[0]
    prev = rows[1] if len(rows) > 1 else None
    return _PricePoint(
        symbol=symbol,
        time=latest["time"],
        close=Decimal(str(latest["close"])),
        prev_close=Decimal(str(prev["close"])) if prev else None,
    )


async def _overnight_moves(db: AsyncSession) -> list[dict[str, Any]]:
    symbols = [
        ("BTC/USD", "Bitcoin"),
        ("ETH/USD", "Ether"),
        ("SOL/USD", "Solana"),
        ("^GSPC", "S&P 500"),
        ("^NSEI", "Nifty 50"),
        ("USDINR=X", "USDINR"),
    ]
    out: list[dict[str, Any]] = []
    for sym, label in symbols:
        pt = await _latest_two(db, sym)
        if pt is None:
            continue
        out.append(
            {
                "symbol": sym,
                "label": label,
                "time": pt.time,
                "close": float(pt.close),
                "pct_change": pt.pct_change,
            }
        )
    return out


async def _economic_calendar(db: AsyncSession, day: datetime) -> list[dict[str, Any]]:
    """Pull HIGH-impact events from the news table (economic calendar shows up
    as ``category='econ_calendar'`` after Stage 2 ingest)."""
    start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    try:
        stmt = sql_text("""
            SELECT id, time, title, url, source, symbol, impact_score
            FROM news
            WHERE category = 'econ_calendar'
              AND time >= :start AND time < :end
              AND (impact_score IS NULL OR impact_score >= 0.7)
            ORDER BY time ASC
            LIMIT 20
            """)
        rows = list((await db.execute(stmt, {"start": start, "end": end})).mappings())
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"econ_calendar fetch failed: {exc}")
        return []
    return [dict(r) for r in rows]


async def _top_news_per_watchlist(
    db: AsyncSession, limit_per: int = 3
) -> dict[str, list[dict[str, Any]]]:
    try:
        wl_stmt = sql_text("SELECT symbol FROM watchlist ORDER BY added_at DESC LIMIT 10")
        watchlist = [r["symbol"] for r in (await db.execute(wl_stmt)).mappings()]
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"watchlist fetch failed: {exc}")
        return {}
    if not watchlist:
        return {}
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=1)
    out: dict[str, list[dict[str, Any]]] = {}
    for sym in watchlist:
        try:
            stmt = sql_text("""
                SELECT id, time, title, url, source, sentiment, impact_score
                FROM news
                WHERE symbol = :sym AND time >= :cutoff
                ORDER BY (COALESCE(impact_score, 0) * 0.6 +
                         COALESCE(ABS(sentiment), 0) * 0.4) DESC,
                         time DESC
                LIMIT :limit
                """)
            rows = list(
                (
                    await db.execute(stmt, {"sym": sym, "cutoff": cutoff, "limit": limit_per})
                ).mappings()
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"news fetch for {sym} failed: {exc}")
            rows = []
        if rows:
            out[sym] = [dict(r) for r in rows]
    return out


async def _regime_per_market(db: AsyncSession) -> list[dict[str, Any]]:
    try:
        stmt = sql_text("""
            SELECT DISTINCT ON (symbol) id, symbol, regime, since, confidence
            FROM regime
            ORDER BY symbol, since DESC
            """)
        return [dict(r) for r in (await db.execute(stmt)).mappings()]
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"regime fetch failed: {exc}")
        return []


async def _watchlist_deltas(db: AsyncSession) -> list[dict[str, Any]]:
    try:
        wl_stmt = sql_text("SELECT symbol FROM watchlist LIMIT 25")
        symbols = [r["symbol"] for r in (await db.execute(wl_stmt)).mappings()]
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"watchlist fetch (deltas) failed: {exc}")
        return []
    out: list[dict[str, Any]] = []
    for sym in symbols:
        pt = await _latest_two(db, sym)
        if pt is None or pt.pct_change is None:
            continue
        # unusual volume: latest volume vs 20-day avg
        try:
            vstmt = sql_text("""
                SELECT volume FROM ohlcv
                WHERE symbol = :sym AND timeframe = '1d'
                ORDER BY time DESC
                LIMIT 20
                """)
            vols = [float(r["volume"]) for r in (await db.execute(vstmt, {"sym": sym})).mappings()]
        except Exception:  # noqa: BLE001
            vols = []
        unusual = False
        if len(vols) >= 5:
            latest = vols[0]
            avg = sum(vols[1:]) / max(1, len(vols) - 1)
            unusual = avg > 0 and latest > avg * 1.8
        out.append(
            {
                "symbol": sym,
                "pct_change": pt.pct_change,
                "close": float(pt.close),
                "unusual_volume": unusual,
            }
        )
    # biggest movers: sorted by abs pct change
    out.sort(key=lambda r: abs(r.get("pct_change") or 0.0), reverse=True)
    return out[:10]


async def _open_position_risk(db: AsyncSession) -> dict[str, Any]:
    try:
        stmt = sql_text("""
            SELECT COUNT(*) AS n_open,
                   COALESCE(SUM(cost_basis_inr), 0) AS gross_inr
            FROM holdings
            WHERE closed_at IS NULL
            """)
        row = (await db.execute(stmt)).mappings().first()
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"open_position_risk failed: {exc}")
        return {}
    return dict(row) if row else {}


async def _calibration_breach(db: AsyncSession) -> list[dict[str, Any]]:
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=35)
    try:
        stmt = sql_text("""
            SELECT DISTINCT ON (model_name, model_version)
                   id, model_name, model_version, as_of, ece, brier_score
            FROM calibration
            WHERE as_of >= :cutoff
            ORDER BY model_name, model_version, as_of DESC
            """)
        rows = [dict(r) for r in (await db.execute(stmt, {"cutoff": cutoff})).mappings()]
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"calibration fetch failed: {exc}")
        return []
    return [r for r in rows if r.get("ece") is not None and r["ece"] > 0.15]


async def _shadow_vs_actual(db: AsyncSession) -> dict[str, Any]:
    try:
        actual_stmt = sql_text(
            "SELECT COUNT(*) AS n, COALESCE(SUM(amount_inr),0) AS gross FROM portfolio_tx"
        )
        shadow_stmt = sql_text(
            "SELECT COUNT(*) AS n, COALESCE(SUM(amount_inr),0) AS gross FROM shadow_portfolio_tx"
        )
        a = (await db.execute(actual_stmt)).mappings().first()
        s = (await db.execute(shadow_stmt)).mappings().first()
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"shadow_vs_actual failed: {exc}")
        return {}
    return {
        "actual_tx": a["n"] if a else 0,
        "shadow_tx": s["n"] if s else 0,
        "actual_gross": float(a["gross"]) if a else 0.0,
        "shadow_gross": float(s["gross"]) if s else 0.0,
    }


# ---------------------------------------------------------------------------
# LLM narrative (optional connective tissue)
# ---------------------------------------------------------------------------


async def _llm_topline(data_block: str) -> str:
    """Ask the LLM for a one-line skim summary. Falls back silently if unavailable.

    Routes via the multi-provider client at ``TaskType.MORNING_BRIEF`` with
    ``Sensitivity.SENSITIVE`` — the morning brief surfaces user holdings in
    section 6, so the prose layer must respect the same privacy boundary.
    Under ``LLM_PRIVACY_STRICT=true`` (default) this pins to local Ollama;
    set strict=false in your env to route the prose to Groq.
    """
    try:
        system = load_prompt("morning_brief_system")
        client = get_llm_client()
        messages = [
            ChatMessage(role="system", content=system),
            ChatMessage(
                role="user",
                content=(
                    "Below is the structured morning-brief data block. Write ONE short "
                    "opening line (≤ 25 words) summarising the most important move or "
                    "alignment, if any. Cite one source.\n\n"
                    f"{data_block}"
                ),
            ),
        ]
        text = await client.complete(
            messages,
            task=TaskType.MORNING_BRIEF,
            sensitivity=Sensitivity.SENSITIVE,
            max_tokens=120,
            temperature=0.3,
        )
        return text.strip()
    except (LLMUnavailable, LLMAllProvidersFailed) as exc:
        logger.debug(f"LLM topline skipped (unavailable): {exc}")
        return "_(LLM unavailable — data-only brief.)_"
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"LLM topline failed: {exc}")
        return "_(LLM error — data-only brief.)_"


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _fmt_pct(p: float | None) -> str:
    if p is None:
        return "n/a"
    sign = "+" if p >= 0 else ""
    return f"{sign}{p:.2f}%"


def _section1(overnight: list[dict[str, Any]]) -> str:
    if not overnight:
        return "## 1. Overnight moves\n\n_No OHLCV rows — run ingest flows._\n"
    lines = ["## 1. Overnight moves", ""]
    for row in overnight:
        lines.append(
            f"- **{row['label']}** ({row['symbol']}): `{row['close']:,.4f}` "
            f"({_fmt_pct(row['pct_change'])}) "
            f"[`db://ohlcv/{row['symbol']}@{row['time'].isoformat()}`]"
        )
    return "\n".join(lines) + "\n"


def _section2(events: list[dict[str, Any]]) -> str:
    if not events:
        return "## 2. Economic calendar today\n\n_No HIGH-impact events ingested for today._\n"
    lines = ["## 2. Economic calendar today (HIGH impact)", ""]
    for e in events:
        imp = e.get("impact_score")
        lines.append(
            f"- **{e['time'].strftime('%H:%M UTC')}** · {e['title']} "
            f"({e['source']}) [src]({e['url']}) _(impact {imp})_"
        )
    return "\n".join(lines) + "\n"


def _section3(news_map: dict[str, list[dict[str, Any]]]) -> str:
    if not news_map:
        return "## 3. Top 3 overnight news per watchlist\n\n_No watchlist or no recent news._\n"
    lines = ["## 3. Top 3 overnight news per watchlist", ""]
    for sym, rows in news_map.items():
        lines.append(f"### {sym}")
        for r in rows:
            sent = r.get("sentiment")
            arrow = "+" if (sent or 0) > 0.1 else "-" if (sent or 0) < -0.1 else "~"
            lines.append(f"- [{arrow}] {r['title']} ([{r['source']}]({r['url']}))")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _section4(regimes: list[dict[str, Any]]) -> str:
    if not regimes:
        return "## 4. Regime state per market\n\n_Regime classifier not yet populated._\n"
    lines = ["## 4. Regime state per market", ""]
    for r in regimes:
        lines.append(
            f"- **{r['symbol']}**: `{r['regime']}` since "
            f"{r['since'].strftime('%Y-%m-%d')} "
            f"(confidence {float(r['confidence']):.0%}) "
            f"[`db://regime/{r['id']}`]"
        )
    return "\n".join(lines) + "\n"


def _section5(deltas: list[dict[str, Any]]) -> str:
    if not deltas:
        return "## 5. Watchlist deltas\n\n_Empty watchlist or no OHLCV for watchlist symbols._\n"
    lines = ["## 5. Watchlist deltas (biggest movers · unusual volume flagged)", ""]
    for r in deltas:
        flag = " · ⚡ unusual vol" if r["unusual_volume"] else ""
        lines.append(
            f"- **{r['symbol']}**: `{r['close']:,.4f}` ({_fmt_pct(r['pct_change'])}){flag}"
        )
    return "\n".join(lines) + "\n"


def _section6(risk: dict[str, Any]) -> str:
    lines = ["## 6. Open-position risk snapshot", ""]
    if not risk:
        lines.append("_No holdings table data._")
    else:
        lines.append(f"- Open positions: **{risk.get('n_open', 0)}**")
        lines.append(f"- Gross invested (INR): **₹{float(risk.get('gross_inr', 0) or 0):,.0f}**")
        lines.append("- Drawdown halt: see portfolio service (`db://holdings`).")
    return "\n".join(lines) + "\n"


def _section7(breaches: list[dict[str, Any]]) -> str:
    lines = ["## 7. Calibration note", ""]
    if not breaches:
        lines.append("- No models breached ECE threshold in the last monthly run.")
    else:
        for b in breaches:
            lines.append(
                f"- **{b['model_name']} v{b['model_version']}** ECE={b['ece']:.3f} "
                f"(Brier {b['brier_score']:.3f}) "
                f"[`db://calibration/{b['id']}`]"
            )
    return "\n".join(lines) + "\n"


def _section8(s: dict[str, Any]) -> str:
    if not s:
        return "## 8. Shadow vs actual\n\n_No shadow ledger data yet._\n"
    delta = s["shadow_tx"] - s["actual_tx"]
    sign = "+" if delta >= 0 else ""
    return (
        "## 8. Shadow vs actual\n\n"
        f"- Shadow ledger executed **{sign}{delta}** more txns than actual "
        f"in trailing period (shadow={s['shadow_tx']}, actual={s['actual_tx']}).\n"
    )


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


async def build_morning_brief(db: AsyncSession, target: datetime) -> str:
    """Build the morning brief for ``target`` date (UTC start-of-day)."""
    now = datetime.now(tz=timezone.utc)

    overnight = await _overnight_moves(db)
    events = await _economic_calendar(db, target)
    news_map = await _top_news_per_watchlist(db)
    regimes = await _regime_per_market(db)
    deltas = await _watchlist_deltas(db)
    risk = await _open_position_risk(db)
    breaches = await _calibration_breach(db)
    shadow = await _shadow_vs_actual(db)

    # Build compact data block for LLM topline.
    data_block = (
        f"Overnight: {overnight[:3]}\n"
        f"Regimes: {regimes[:5]}\n"
        f"Calibration breaches: {[b['model_name'] for b in breaches]}\n"
    )
    topline = await _llm_topline(data_block)

    header = (
        f"# PFIP Morning Brief — {target.date().isoformat()}\n\n"
        f"_Generated {now.isoformat()} UTC_\n\n"
        f"> **Topline:** {topline}\n\n"
    )
    body = "\n".join(
        [
            _section1(overnight),
            _section2(events),
            _section3(news_map),
            _section4(regimes),
            _section5(deltas),
            _section6(risk),
            _section7(breaches),
            _section8(shadow),
        ]
    )
    footer = "\n---\n" "<!-- TODO(user): trim the sections you don't read each morning. -->\n"
    return header + body + footer


__all__ = ["build_morning_brief"]
