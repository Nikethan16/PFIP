"""Telegram public-channel reader via Telethon.

Requires TELEGRAM_API_ID and TELEGRAM_API_HASH. On first run, Telethon prompts
for a phone code; inside a headless container you should run it once locally
with ``TELEGRAM_SESSION_PATH`` to seed the session file, then mount the
session into the container.

Respects flood-wait errors by sleeping the suggested seconds.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker
from pfip.ingest._common.upsert import upsert_news

log = get_logger("pfip.ingest.news.telegram_telethon")

# Curated list per plan §5.3 — edit in .env via TELEGRAM_CHANNELS (comma-sep).
DEFAULT_CHANNELS: tuple[str, ...] = (
    "ZeroHedgeCryptoNews",
    "cryptocom",
    "binanceannouncements",
    "CoinDeskTelegram",
)


async def _read_channel(client: Any, username: str, limit: int = 50) -> list[dict[str, Any]]:
    from telethon.errors import FloodWaitError  # type: ignore

    try:
        entity = await client.get_entity(username)
    except Exception as e:  # noqa: BLE001
        log.warning(f"telegram: resolve {username} failed: {type(e).__name__}: {e}")
        return []
    msgs: list[dict[str, Any]] = []
    try:
        async for msg in client.iter_messages(entity, limit=limit):
            if not msg.message:
                continue
            t = msg.date
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            url = f"https://t.me/{username}/{msg.id}"
            msgs.append(
                {
                    "time": t,
                    "title": msg.message.split("\n", 1)[0][:300],
                    "url": url,
                    "source": f"telegram_{username}",
                    "summary": msg.message[:2000],
                    "category": "social",
                }
            )
    except FloodWaitError as e:  # type: ignore[attr-defined]
        log.warning(f"telegram: flood-wait {e.seconds}s on {username}; sleeping")
        await asyncio.sleep(e.seconds + 1)
    except Exception as e:  # noqa: BLE001
        log.warning(f"telegram: iter {username} failed: {type(e).__name__}: {e}")
    return msgs


async def fetch_telegram(channels: Iterable[str] = DEFAULT_CHANNELS, limit: int = 50) -> list[dict[str, Any]]:
    api_id = os.environ.get("TELEGRAM_API_ID", "").strip()
    api_hash = os.environ.get("TELEGRAM_API_HASH", "").strip()
    session_path = os.environ.get("TELEGRAM_SESSION_PATH", "pfip_telegram")
    if not api_id or not api_hash:
        log.warning("TELEGRAM_API_ID/HASH not set, telegram no-op")
        return []
    try:
        from telethon import TelegramClient  # type: ignore
    except ImportError:
        log.warning("telethon not installed; telegram no-op")
        return []
    try:
        api_id_int = int(api_id)
    except ValueError:
        log.warning("TELEGRAM_API_ID must be an integer")
        return []
    out: list[dict[str, Any]] = []
    async with TelegramClient(session_path, api_id_int, api_hash) as client:
        for ch in channels:
            out.extend(await _read_channel(client, ch, limit=limit))
    return out


async def ingest_telegram(
    channels: Iterable[str] = DEFAULT_CHANNELS,
    limit: int = 50,
    session: AsyncSession | None = None,
) -> int:
    log.info("ingest.telegram starting")
    items = await fetch_telegram(channels, limit)
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            n = await upsert_news(s, items)
    else:
        n = await upsert_news(session, items)
    log.info(f"ingest.telegram done: {n} rows")
    return n
