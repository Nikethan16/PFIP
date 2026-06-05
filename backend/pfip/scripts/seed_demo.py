"""Synthetic demo data seed.

Populates every table on the dashboard with realistic-looking sample data so
the UI can be exercised end-to-end without waiting for real ingest. All
inserted rows carry a ``demo=True`` flag (where the column exists) or use a
sentinel symbol pattern (e.g. ``DEMO-*``) so they're easy to remove later.

Run via:

    docker exec pfip-backend python -m pfip.scripts.seed_demo
    # or via API:
    POST /api/v1/setup/demo

The demo data is deliberately *not* hidden behind a feature flag — it's
real rows in real tables. The frontend should show a "DEMO DATA" banner
when ``GET /api/v1/setup/status`` returns ``demo_mode=true`` (i.e. when
ohlcv rows starting with ``DEMO-`` exist).
"""

from __future__ import annotations

import asyncio
import math
import random
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from loguru import logger
from sqlalchemy import text as sql_text

from pfip.db.session import get_sessionmaker


# Realistic-ish starting prices + daily volatility for the demo assets.
ASSETS: list[tuple[str, str, str, float, float]] = [
    # (symbol, market, source, start_price, daily_vol)
    ("DEMO-BTC-USD", "crypto", "demo", 67_500.00, 0.025),
    ("DEMO-ETH-USD", "crypto", "demo", 3_400.00, 0.030),
    ("DEMO-SOL-USD", "crypto", "demo", 168.00, 0.040),
    ("DEMO-SPY", "us_equity", "demo", 540.00, 0.010),
    ("DEMO-NVDA", "us_equity", "demo", 875.00, 0.025),
    ("DEMO-RELIANCE", "india_equity", "demo", 2_850.00, 0.012),
    ("DEMO-TCS", "india_equity", "demo", 3_950.00, 0.011),
]

NEWS_SEEDS = [
    ("DEMO-BTC-USD", "BTC clears $68k as ETF inflows accelerate", 0.45, 0.82),
    ("DEMO-BTC-USD", "Whale wallet activity hits 6-month high", 0.20, 0.65),
    ("DEMO-ETH-USD", "Ethereum gas fees drop 30% post-upgrade", 0.30, 0.70),
    ("DEMO-SOL-USD", "Solana DEX volumes set quarterly record", 0.35, 0.55),
    ("DEMO-NVDA", "NVIDIA Q4 beat: data center revenue +120% YoY", 0.70, 0.95),
    ("DEMO-SPY", "Fed signals one rate cut at September FOMC", 0.15, 0.85),
    ("DEMO-RELIANCE", "Reliance Jio adds 12M subscribers in Q2", 0.40, 0.60),
    ("DEMO-TCS", "TCS announces $2B share buyback at ₹4,500", 0.55, 0.80),
]


async def _seed_ohlcv(session) -> int:
    """Generate 90 days of daily OHLCV per demo asset via random walk."""
    rng = random.Random(42)
    n = 0
    now = datetime.now(tz=timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    for symbol, market, source, start_price, vol in ASSETS:
        price = start_price
        for d in range(90, 0, -1):
            t = now - timedelta(days=d)
            ret = rng.gauss(0.0003, vol)
            open_p = price
            close_p = price * (1 + ret)
            high_p = max(open_p, close_p) * (1 + abs(rng.gauss(0, vol / 3)))
            low_p = min(open_p, close_p) * (1 - abs(rng.gauss(0, vol / 3)))
            volume = rng.uniform(0.5e6, 5e6)
            await session.execute(
                sql_text(
                    """
                    INSERT INTO ohlcv (time, symbol, market, source, timeframe,
                                       open, high, low, close, volume)
                    VALUES (:t, :s, :m, :src, '1d',
                            :o, :h, :l, :c, :v)
                    ON CONFLICT (time, symbol, source, timeframe) DO NOTHING
                    """
                ),
                {
                    "t": t,
                    "s": symbol,
                    "m": market,
                    "src": source,
                    "o": Decimal(str(round(open_p, 6))),
                    "h": Decimal(str(round(high_p, 6))),
                    "l": Decimal(str(round(low_p, 6))),
                    "c": Decimal(str(round(close_p, 6))),
                    "v": Decimal(str(round(volume, 2))),
                },
            )
            n += 1
            price = close_p
    await session.commit()
    return n


async def _seed_watchlist(session) -> int:
    """Add the demo assets to the watchlist so the UI surfaces them."""
    n = 0
    for symbol, market, _src, _p, _v in ASSETS:
        try:
            await session.execute(
                sql_text(
                    """
                    INSERT INTO watchlist (symbol, market, note, added_at)
                    VALUES (:s, :m, 'demo seed', :now)
                    ON CONFLICT (symbol, market) DO NOTHING
                    """
                ),
                {"s": symbol, "m": market, "now": datetime.now(tz=timezone.utc)},
            )
            n += 1
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"watchlist insert failed for {symbol}: {exc}")
    await session.commit()
    return n


async def _seed_news(session) -> int:
    """Drop in ~24 news items across the demo assets."""
    n = 0
    now = datetime.now(tz=timezone.utc)
    for symbol, title, sentiment, impact in NEWS_SEEDS:
        for hours_back in (1, 6, 18):
            t = now - timedelta(hours=hours_back)
            try:
                await session.execute(
                    sql_text(
                        """
                        INSERT INTO news (time, symbol, source, title, url,
                                          sentiment, impact_score, category)
                        VALUES (:t, :s, 'demo', :title, :url,
                                :sent, :imp, 'demo')
                        ON CONFLICT DO NOTHING
                        """
                    ),
                    {
                        "t": t,
                        "s": symbol,
                        "title": f"[DEMO {hours_back}h] {title}",
                        "url": f"https://demo.local/{symbol}/{hours_back}h",
                        "sent": sentiment + (hours_back * 0.01),  # slight variation
                        "imp": impact,
                    },
                )
                n += 1
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"news insert failed: {exc}")
    await session.commit()
    return n


async def _seed_regime(session) -> int:
    """One regime label per demo asset."""
    regimes = ["bull_trend", "sideways", "high_volatility", "bull_trend",
               "bull_trend", "sideways", "sideways"]
    now = datetime.now(tz=timezone.utc)
    n = 0
    for (symbol, _m, _src, _p, _v), regime in zip(ASSETS, regimes, strict=False):
        try:
            await session.execute(
                sql_text(
                    """
                    INSERT INTO regime (symbol, regime, since, confidence, model_name, model_version)
                    VALUES (:s, :r, :since, :conf, 'demo_hmm', 'v0-demo')
                    ON CONFLICT DO NOTHING
                    """
                ),
                {
                    "s": symbol,
                    "r": regime,
                    "since": now - timedelta(days=3),
                    "conf": 0.78,
                },
            )
            n += 1
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"regime insert failed for {symbol}: {exc}")
    await session.commit()
    return n


async def _seed_signals(session) -> int:
    """A couple of fresh-ish signals so the Signals page renders."""
    now = datetime.now(tz=timezone.utc)
    rows = [
        ("DEMO-BTC-USD", "BUY", 78, 24,
         [("rsi_14", 0.32), ("macd", 0.18), ("on_chain_netflow", 0.15)],
         [("funding_rate", -0.12), ("vix", -0.08)]),
        ("DEMO-NVDA", "BUY", 71, 72,
         [("earnings_surprise", 0.42), ("price_above_50ma", 0.21)],
         [("p_e_ratio", -0.18)]),
        ("DEMO-SOL-USD", "HOLD", 58, 24,
         [("realized_vol_30d", 0.20), ("regime_high_vol", 0.30)],
         [("price_momentum", -0.15)]),
        ("DEMO-RELIANCE", "BUY", 66, 168,
         [("eps_growth_yoy", 0.28), ("oi_buildup", 0.22)],
         [("crude_oil_correlation", -0.20)]),
    ]
    n = 0
    for symbol, direction, conf, horizon, drivers, counters in rows:
        try:
            await session.execute(
                sql_text(
                    """
                    INSERT INTO signals
                        (generated_at, asset, direction, confidence, horizon_hours,
                         drivers, counter_arguments, regime, model_name, model_version)
                    VALUES (:t, :a, :d, :c, :h,
                            :drivers::jsonb, :counters::jsonb, :r, 'demo_lgbm', 'v0-demo')
                    """
                ),
                {
                    "t": now - timedelta(hours=2),
                    "a": symbol,
                    "d": direction,
                    "c": conf,
                    "h": horizon,
                    "drivers": _jsonify_drivers(drivers),
                    "counters": _jsonify_drivers(counters),
                    "r": "bull_trend",
                },
            )
            n += 1
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"signal insert failed for {symbol}: {exc}")
    await session.commit()
    return n


def _jsonify_drivers(items: list[tuple[str, float]]) -> str:
    import json
    return json.dumps([{"feature": f, "contribution": c} for f, c in items])


async def _seed_holdings(session) -> int:
    """A handful of mock holdings across categories so portfolio page renders."""
    now = datetime.now(tz=timezone.utc)
    rows = [
        ("equity", "DEMO-RELIANCE", "Zerodha", 50, 142_500),
        ("equity", "DEMO-TCS", "Zerodha", 25, 98_750),
        ("crypto_exchange", "DEMO-BTC-USD", "CoinDCX", Decimal("0.05"), 240_000),
        ("crypto_self_custody", "DEMO-ETH-USD", "Ledger", Decimal("0.8"), 215_000),
        ("mutual_fund", "DEMO_PPFAS_FLEXI", "Direct", 1850, 165_000),
        ("us_equity_indian_broker", "DEMO-NVDA", "INDmoney", 8, 580_000),
    ]
    n = 0
    for category, symbol, broker, qty, cost in rows:
        try:
            await session.execute(
                sql_text(
                    """
                    INSERT INTO holdings (category, symbol, broker, acquired_at,
                                          qty, cost_basis_inr, cost_basis_ccy, is_self_custody, notes)
                    VALUES (:c, :s, :b, :acq, :q, :cb, 'INR',
                            :scc, 'demo seed')
                    ON CONFLICT DO NOTHING
                    """
                ),
                {
                    "c": category,
                    "s": symbol,
                    "b": broker,
                    "acq": now - timedelta(days=60),
                    "q": Decimal(str(qty)),
                    "cb": Decimal(str(cost)),
                    "scc": category == "crypto_self_custody",
                },
            )
            n += 1
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"holding insert failed for {symbol}: {exc}")
    await session.commit()
    return n


async def seed_demo() -> dict[str, int]:
    """Public entrypoint. Returns row counts per table seeded."""
    factory = get_sessionmaker()
    counts: dict[str, int] = {}
    async with factory() as session:
        counts["ohlcv"] = await _seed_ohlcv(session)
        counts["watchlist"] = await _seed_watchlist(session)
        counts["news"] = await _seed_news(session)
        counts["regime"] = await _seed_regime(session)
        counts["signals"] = await _seed_signals(session)
        counts["holdings"] = await _seed_holdings(session)
    return counts


async def clear_demo() -> dict[str, int]:
    """Reverse the demo seed. Removes everything matching DEMO-* sentinel."""
    factory = get_sessionmaker()
    counts: dict[str, int] = {}
    async with factory() as session:
        for table, where in [
            ("ohlcv", "symbol LIKE 'DEMO-%' OR source = 'demo'"),
            ("watchlist", "symbol LIKE 'DEMO-%'"),
            ("news", "source = 'demo' OR category = 'demo'"),
            ("regime", "symbol LIKE 'DEMO-%'"),
            ("signals", "asset LIKE 'DEMO-%'"),
            ("holdings", "symbol LIKE 'DEMO-%' OR notes = 'demo seed'"),
        ]:
            try:
                result = await session.execute(sql_text(f"DELETE FROM {table} WHERE {where}"))
                counts[table] = result.rowcount or 0
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"clear_demo on {table} failed: {exc}")
                counts[table] = -1
        await session.commit()
    return counts


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="PFIP demo seed")
    parser.add_argument("--clear", action="store_true", help="remove demo data instead of seeding")
    args = parser.parse_args()
    fn = clear_demo if args.clear else seed_demo
    try:
        counts = asyncio.run(fn())
    except Exception as exc:  # noqa: BLE001
        logger.error(f"demo seed failed: {type(exc).__name__}: {exc}")
        return 1
    action = "Cleared" if args.clear else "Seeded"
    for table, n in counts.items():
        logger.info(f"  {action} {table}: {n} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
