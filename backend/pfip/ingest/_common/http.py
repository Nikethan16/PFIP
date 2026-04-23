"""Shared HTTP client helpers for ingest adapters.

All external HTTP should go through ``get_async_client`` to get:
- a consistent User-Agent identifying the PFIP project,
- sensible default timeouts,
- a reusable context manager.

The ``retry_http`` decorator wraps an async function with tenacity-based
exponential backoff (3 attempts) for httpx.HTTPError.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

USER_AGENT = "PFIP/0.1 (+https://github.com/cbcinc/pfip; contact: suresh.sahoo@cbcinc.ai)"

DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


@asynccontextmanager
async def get_async_client(
    *,
    headers: dict[str, str] | None = None,
    timeout: httpx.Timeout | float | None = None,
    follow_redirects: bool = True,
    **kwargs: Any,
) -> AsyncIterator[httpx.AsyncClient]:
    """Yield a configured httpx.AsyncClient.

    Merges a standard User-Agent header with any caller-provided headers.
    """
    merged: dict[str, str] = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        merged.update(headers)
    async with httpx.AsyncClient(
        headers=merged,
        timeout=timeout if timeout is not None else DEFAULT_TIMEOUT,
        follow_redirects=follow_redirects,
        **kwargs,
    ) as client:
        yield client


def retry_http(max_attempts: int = 3, base_seconds: float = 1.0):  # type: ignore[no-untyped-def]
    """Decorator factory — retries an async callable on httpx errors with exp backoff."""

    def decorator(fn):  # type: ignore[no-untyped-def]
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(max_attempts),
                wait=wait_exponential(multiplier=base_seconds, min=base_seconds, max=30),
                retry=retry_if_exception_type(
                    (httpx.HTTPError, httpx.ReadTimeout, httpx.ConnectError)
                ),
                reraise=True,
            ):
                with attempt:
                    return await fn(*args, **kwargs)

        wrapper.__name__ = fn.__name__
        wrapper.__doc__ = fn.__doc__
        return wrapper

    return decorator
