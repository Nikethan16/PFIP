"""Integration-test fixtures — real async SQLAlchemy session on a throwaway Postgres.

Why this exists
---------------
The rest of the suite runs against a ``_FakeSession`` (see
``backend/tests/conftest.py``), so the SQL layer is *never executed*. That is how
the ``OHLCVRow.ts`` synonym bug and the FX-rate lookup bug shipped — both were
SQL/DDL-level problems invisible to a fake session.

These fixtures give tests a genuine Postgres so the actual ``select(...)`` /
``DISTINCT ON`` / ``ON CONFLICT`` statements are exercised.

The skip-gate + DB-URL resolution lives in ``_harness.require_db`` (a plain
helper module, because raising ``Skipped`` during *conftest import* is a
collection error rather than a graceful skip). Each integration test module calls
``require_db()`` at module scope; these fixtures reuse the resolved URL.

Schema strategy
---------------
The production migrations require TimescaleDB + pgcrypto extensions and create
hypertables, which a vanilla ``postgres:16`` image does not have. So we do NOT
run ``alembic upgrade head``. Instead we ``Base.metadata.create_all`` the ORM
tables (fast, covers every model the tests touch) and run a little extra raw DDL
for ``fx_rates`` (which exists only as an Alembic migration, no ORM model).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from tests.integration import _harness

# Mirrors migration 0006's ``fx_rates`` definition (no ORM model exists for it).
_EXTRA_DDL = (
    """
    CREATE TABLE IF NOT EXISTS fx_rates (
        rate_date   DATE          NOT NULL,
        base        VARCHAR(8)    NOT NULL,
        quote       VARCHAR(8)    NOT NULL,
        rate        NUMERIC(20, 8) NOT NULL,
        source      VARCHAR       NOT NULL,
        ingested_at TIMESTAMPTZ   NOT NULL DEFAULT now(),
        PRIMARY KEY (rate_date, base, quote, source)
    )
    """,
)


@pytest.fixture(scope="session")
def _engine():
    """Session-scoped async engine + schema bootstrap.

    Skips cleanly (via ``require_db``) if no DB is available — though by the time
    a fixture runs, the module-level ``require_db()`` call has already gated it.
    """
    import asyncio

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    url = _harness.require_db()

    # Importing the models package registers every table on ``Base.metadata``.
    import pfip.models  # noqa: F401
    from pfip.db.base import Base

    engine = create_async_engine(url, future=True, pool_pre_ping=True)

    async def _bootstrap() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            for ddl in _EXTRA_DDL:
                await conn.execute(text(ddl))

    asyncio.run(_bootstrap())
    yield engine

    async def _dispose() -> None:
        await engine.dispose()

    asyncio.run(_dispose())

    if _harness.PG_CONTAINER is not None:
        _harness.PG_CONTAINER.stop()


@pytest.fixture
async def db_session(_engine) -> AsyncIterator[AsyncSession]:  # noqa: F821
    """A fresh ``AsyncSession`` per test with the relevant tables truncated.

    Truncating up-front (rather than after) keeps each test independent even if a
    prior test failed mid-way and left rows behind.
    """
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    maker = async_sessionmaker(bind=_engine, expire_on_commit=False, class_=AsyncSession)

    # portfolio_tx references holdings(id) — RESTART IDENTITY + CASCADE so order
    # doesn't matter and FKs don't block the truncate.
    async with _engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE TABLE ohlcv, portfolio_tx, holdings, fx_rates " "RESTART IDENTITY CASCADE"
            )
        )

    async with maker() as session:
        yield session
        await session.rollback()
