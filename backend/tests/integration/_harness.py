"""Shared skip-gate + DB-URL resolution for the real-DB integration suite.

This logic lives in a plain helper module (not ``conftest.py``) because raising
``Skipped`` *during conftest import* is treated by pytest as a collection error,
not a graceful skip. Instead, each integration test module calls
:func:`require_db` at module scope::

    from tests.integration._harness import require_db
    DATABASE_URL = require_db()  # skips the whole module if no DB is available

``conftest.py`` then reuses :data:`RESOLVED_URL` for its fixtures.

Resolution order
----------------
1. ``DATABASE_URL`` env var (CI ``services: postgres``) — used directly, **but
   only when it is safe to truncate** (see the safety gate below).
2. A ``postgres:16`` container via ``testcontainers``.
3. Neither available → ``pytest.skip(..., allow_module_level=True)``.

Safety gate (why it exists)
---------------------------
``conftest.py`` *truncates* ``ohlcv, portfolio_tx, holdings, fx_rates`` before
each test. If ``DATABASE_URL`` happens to point at a real/managed database
(e.g. a Neon production URL exported into the shell), an innocent ``pytest``
would silently wipe live data. So we only honour an env ``DATABASE_URL`` when it
is obviously a throwaway — a ``localhost``/``127.0.0.1`` host (CI service
container or a local dev Postgres) — unless the operator explicitly opts in via
``PFIP_ALLOW_DESTRUCTIVE_DB_TESTS=1``. Any other host skips the module with a
clear reason rather than risking destruction.
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit

import pytest

# Populated by require_db(); conftest reads these.
RESOLVED_URL: str | None = None
PG_CONTAINER = None  # the testcontainers handle, when we started one

_ENV_URL = os.environ.get("DATABASE_URL")
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", ""}


def _is_throwaway(url: str) -> bool:
    """True when ``url`` is safe to truncate without an explicit override.

    A throwaway DB is one on the local machine (CI's ``services: postgres`` maps
    to ``localhost``; a dev Postgres is the same). Managed hosts (Neon, RDS, …)
    are not throwaway and require ``PFIP_ALLOW_DESTRUCTIVE_DB_TESTS=1``.
    """
    if os.environ.get("PFIP_ALLOW_DESTRUCTIVE_DB_TESTS") == "1":
        return True
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return False
    return host in _LOCAL_HOSTS


def _normalize_async_url(url: str) -> str:
    """Coerce any Postgres URL into the ``postgresql+psycopg`` async form the
    app itself uses (psycopg3 is the installed async driver)."""
    for prefix in (
        "postgresql+asyncpg://",
        "postgresql+psycopg2://",
        "postgresql://",
        "postgres://",
    ):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url  # already postgresql+psycopg:// or something exotic we leave as-is


def require_db() -> str:
    """Resolve a usable async DB URL or skip the calling module cleanly.

    Idempotent: the container (if any) is started only once per process.
    """
    global RESOLVED_URL, PG_CONTAINER
    if RESOLVED_URL is not None:
        return RESOLVED_URL

    if _ENV_URL:
        if not _is_throwaway(_ENV_URL):
            pytest.skip(
                "DATABASE_URL points at a non-local DB; refusing to run "
                "destructive integration tests against it (they TRUNCATE tables). "
                "Set PFIP_ALLOW_DESTRUCTIVE_DB_TESTS=1 to override, or point "
                "DATABASE_URL at a throwaway localhost Postgres.",
                allow_module_level=True,
            )
        RESOLVED_URL = _normalize_async_url(_ENV_URL)
        return RESOLVED_URL

    # No env URL → need Docker via testcontainers.
    pytest.importorskip(
        "testcontainers",
        reason="testcontainers not installed — real-DB integration tests skipped",
    )
    try:
        from testcontainers.postgres import PostgresContainer

        container = PostgresContainer("postgres:16-alpine")
        container.start()
    except Exception as exc:  # — Docker down, image pull fails, etc.
        pytest.skip(
            f"Real-DB integration tests skipped (no usable Postgres: {exc!r})",
            allow_module_level=True,
        )
    PG_CONTAINER = container
    RESOLVED_URL = _normalize_async_url(container.get_connection_url())
    return RESOLVED_URL
