"""Shared pytest fixtures.

The smoke tests intentionally avoid touching the database — they just ensure
every router responds with a sane status code (200 for open routes, 401 for
gated ones without auth). Anything that would hit the DB is monkey-patched to
yield a no-op session. The LLM router is stubbed so tests never touch
Ollama / Groq over the network.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient

from pfip.api.deps import get_db
from pfip.api.main import app
from pfip.core.config import get_settings


class _FakeScalars:
    def all(self_s):  # noqa: ANN001
        return []

    def first(self_s):  # noqa: ANN001
        return None


class _FakeMappings:
    def all(self):
        return []

    def first(self):
        return None

    def __iter__(self):
        return iter([])


class _FakeResult:
    def all(self):
        # Column-select queries (e.g. /assets/search) call ``.all()`` directly
        # on the result rather than via ``.scalars()``.
        return []

    def scalars(self):
        return _FakeScalars()

    def scalar_one(self):
        return 1

    def scalar(self):
        return None

    def mappings(self):
        return _FakeMappings()

    def __iter__(self):
        return iter([])


class _FakeSession:
    """Minimal async-session stand-in for smoke tests."""

    async def execute(self, *args, **kwargs):  # noqa: ANN002, ANN003, D401
        return _FakeResult()

    async def get(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return None

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def refresh(self, _obj) -> None:  # noqa: ANN001
        return None

    def add(self, _obj) -> None:  # noqa: ANN001
        return None

    async def delete(self, _obj) -> None:  # noqa: ANN001
        return None


async def _fake_db() -> AsyncIterator[_FakeSession]:
    yield _FakeSession()


@pytest.fixture(autouse=True)
def _override_db():
    app.dependency_overrides[get_db] = _fake_db
    yield
    app.dependency_overrides.pop(get_db, None)


class _FakeLLMRouter:
    """Stub that never makes a network call.

    Returns a short canned response and an empty embedding so any code path
    that exercises the LLM during tests completes deterministically.
    """

    @property
    def primary_model(self) -> str:
        return "stub"

    @property
    def fallback_model(self) -> str | None:
        return None

    async def generate(self, prompt: str, *, system: str | None = None) -> str:  # noqa: ARG002
        return "_(stub response — LLM mocked in tests.)_"

    async def stream_chat(self, messages):  # noqa: ANN001
        for tok in ["_stub", " ", "tokens", "_"]:
            yield tok

    async def embed(self, text: str) -> list[float]:  # noqa: ARG002
        return [0.0] * 8


@pytest.fixture(autouse=True)
def _override_llm(monkeypatch: pytest.MonkeyPatch):
    """Patch ``get_llm_router`` everywhere it's imported so tests are offline."""
    fake = _FakeLLMRouter()
    import pfip.agent.llm_client as _llm
    import pfip.agent.graph as _graph
    import pfip.agent.morning_brief as _mb
    import pfip.agent.post_mortem as _pm
    import pfip.agent.weekly_review as _wr
    import pfip.agent.arxiv_digest as _ax
    import pfip.kb.search as _kb_search

    for mod in (_llm, _graph, _mb, _pm, _wr, _ax, _kb_search):
        if hasattr(mod, "get_llm_router"):
            monkeypatch.setattr(mod, "get_llm_router", lambda _fake=fake: _fake)
    yield


@pytest.fixture
def client() -> TestClient:
    """Plain TestClient with DB overridden."""
    return TestClient(app)


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """Bearer-token headers for routes that need auth."""
    settings = get_settings()
    now = datetime.now(tz=timezone.utc)
    payload = {
        "sub": settings.pfip_user_email,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=1)).timestamp()),
    }
    token = jwt.encode(payload, settings.nextauth_secret, algorithm=settings.jwt_algorithm)
    return {"Authorization": f"Bearer {token}"}
