"""Unit tests for OHLCV source resolution.

The scheduled compute-features / regime flows must read OHLCV from the *source*
the data was actually ingested under. A static heuristic mislabels US equities
as ``yfinance`` when they live under ``tiingo`` (and NSE names as ``jugaad`` when
they live under ``nse_bhavcopy``), so the heuristic-driven scheduled reads
returned 0 rows for SPY / NVDA / QQQ. :func:`pfip.db.sources.resolve_ohlcv_source`
asks the DB instead; these tests pin its contract and the wiring of both
``run_for_watchlist`` entry points.

The *most-rows* SQL semantics are verified against a real DB in
``tests/integration/test_source_resolution_integration.py``; here we use a fake
session, so we assert the contract (value / None / never-raises) and that each
caller prefers the resolved source over the heuristic.
"""

from __future__ import annotations

from pfip.db.sources import resolve_ohlcv_source


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class _ExecResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeSession:
    """Async-session stand-in whose ``execute`` returns a canned scalar."""

    def __init__(self, *, value=None, raises=False):
        self._value = value
        self._raises = raises

    async def execute(self, *_args, **_kwargs):
        if self._raises:
            raise RuntimeError("simulated DB error / missing table")
        return _ExecResult(self._value)


class _Watch:
    def __init__(self, symbol: str):
        self.symbol = symbol


class _Scalars:
    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items


class _WatchResult:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return _Scalars(self._items)


class _WatchlistSession:
    """Outer session for ``run_for_watchlist``: ``execute`` yields watchlist rows."""

    def __init__(self, symbols):
        self._rows = [_Watch(s) for s in symbols]

    async def execute(self, *_args, **_kwargs):
        return _WatchResult(self._rows)

    async def commit(self):
        # run_for_watchlist now commits right after reading the watchlist to
        # release the read transaction (Neon idle-in-transaction guard). A real
        # AsyncSession has commit(); the fake just needs to accept the call.
        return None


class _DummySymSession:
    """Per-symbol session context manager (features flow opens one per symbol)."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False


# --------------------------------------------------------------------------- #
# resolve_ohlcv_source contract
# --------------------------------------------------------------------------- #
async def test_resolve_returns_db_source() -> None:
    src = await resolve_ohlcv_source(_FakeSession(value="tiingo"), "SPY", "1d")
    assert src == "tiingo"


async def test_resolve_none_when_no_rows() -> None:
    """No OHLCV rows yet -> None so the caller can fall back to a heuristic."""
    src = await resolve_ohlcv_source(_FakeSession(value=None), "NEWSYM", "1d")
    assert src is None


async def test_resolve_never_raises_on_db_error() -> None:
    """A failing query (e.g. missing table) must resolve to None, not raise —
    a best-effort source lookup can't be allowed to abort the whole run."""
    src = await resolve_ohlcv_source(_FakeSession(raises=True), "SPY", "1d")
    assert src is None


# --------------------------------------------------------------------------- #
# The heuristics this DB lookup exists to correct (regression documentation)
# --------------------------------------------------------------------------- #
def test_heuristic_mislabels_us_and_india() -> None:
    """Document *why* the DB lookup is needed: the static heuristics return the
    WRONG source for the markets whose data isn't under the obvious name."""
    from pfip.features.runner import _infer_market_kind, _infer_source
    from pfip.regime.runner import _source_for

    # US equities: heuristic says 'yfinance' but data lives under 'tiingo'.
    assert _infer_market_kind("SPY") == "us"
    assert _infer_source("SPY", "us") == "yfinance"
    assert _source_for("SPY") == "yfinance"

    # NSE: heuristic says 'jugaad' but data lives under 'nse_bhavcopy'.
    assert _infer_market_kind("RELIANCE.NS") == "india"
    assert _infer_source("RELIANCE.NS", "india") == "jugaad"
    assert _source_for("RELIANCE.NS") == "jugaad"


def test_heuristic_is_correct_for_crypto() -> None:
    """Crypto already matches reality ('coinbase'), so the fallback is safe there."""
    from pfip.features.runner import _infer_market_kind, _infer_source
    from pfip.regime.runner import _source_for

    assert _infer_market_kind("BTC-USD") == "crypto"
    assert _infer_source("BTC-USD", "crypto") == "coinbase"
    assert _source_for("BTC-USD") == "coinbase"


# --------------------------------------------------------------------------- #
# features.run_for_watchlist wiring
# --------------------------------------------------------------------------- #
async def test_features_watchlist_uses_resolved_source(monkeypatch) -> None:
    """The feature flow must compute against the RESOLVED source, not 'yfinance'."""
    import pfip.db.session as db_session
    import pfip.features.runner as fr

    captured: dict[str, str] = {}

    async def fake_resolve(_session, _symbol, _tf):
        return "tiingo"

    async def fake_compute(_session, req):
        captured["source"] = req.source
        captured["symbol"] = req.symbol
        return fr.FeatureRunResult(
            symbol=req.symbol,
            source=req.source,
            timeframe=req.timeframe,
            rows_written=1,
            rows_read=1,
            extras_computed=False,
        )

    monkeypatch.setattr(fr, "resolve_ohlcv_source", fake_resolve)
    monkeypatch.setattr(fr, "compute_and_persist", fake_compute)
    monkeypatch.setattr(db_session, "get_sessionmaker", lambda: (lambda: _DummySymSession()))

    out = await fr.run_for_watchlist(_WatchlistSession(["SPY"]))

    assert captured["symbol"] == "SPY"
    assert captured["source"] == "tiingo"  # NOT the 'yfinance' heuristic
    assert [r.symbol for r in out] == ["SPY"]


async def test_features_watchlist_falls_back_to_heuristic_when_no_data(monkeypatch) -> None:
    """With no OHLCV rows the flow still runs, using the static heuristic."""
    import pfip.db.session as db_session
    import pfip.features.runner as fr

    captured: dict[str, str] = {}

    async def fake_resolve(_session, _symbol, _tf):
        return None  # no rows ingested yet

    async def fake_compute(_session, req):
        captured["source"] = req.source
        return fr.FeatureRunResult(
            symbol=req.symbol,
            source=req.source,
            timeframe=req.timeframe,
            rows_written=0,
            rows_read=0,
            extras_computed=False,
        )

    monkeypatch.setattr(fr, "resolve_ohlcv_source", fake_resolve)
    monkeypatch.setattr(fr, "compute_and_persist", fake_compute)
    monkeypatch.setattr(db_session, "get_sessionmaker", lambda: (lambda: _DummySymSession()))

    await fr.run_for_watchlist(_WatchlistSession(["SPY"]))

    assert captured["source"] == "yfinance"  # heuristic fallback for a US ticker


# --------------------------------------------------------------------------- #
# regime.run_for_watchlist wiring
# --------------------------------------------------------------------------- #
async def test_regime_watchlist_uses_resolved_source(monkeypatch) -> None:
    """The regime flow must fit against the RESOLVED source, not 'yfinance'."""
    import pfip.regime.runner as rr
    from pfip.core.contracts import Regime

    captured: dict[str, str] = {}

    async def fake_resolve(_session, _symbol, _tf):
        return "tiingo"

    async def fake_run_for_symbol(_session, **kwargs):
        captured["source"] = kwargs["source"]
        captured["symbol"] = kwargs["symbol"]
        return rr.RegimeRunResult(
            symbol=kwargs["symbol"],
            regime=Regime.SIDEWAYS,
            confidence=0.0,
            state_means={},
            n_obs=0,
            status="ok",
        )

    monkeypatch.setattr(rr, "resolve_ohlcv_source", fake_resolve)
    monkeypatch.setattr(rr, "run_for_symbol", fake_run_for_symbol)

    out = await rr.run_for_watchlist(_WatchlistSession(["SPY"]))

    assert captured["symbol"] == "SPY"
    assert captured["source"] == "tiingo"  # NOT the 'yfinance' heuristic
    assert len(out) == 1


async def test_regime_watchlist_falls_back_to_heuristic_when_no_data(monkeypatch) -> None:
    import pfip.regime.runner as rr
    from pfip.core.contracts import Regime

    captured: dict[str, str] = {}

    async def fake_resolve(_session, _symbol, _tf):
        return None

    async def fake_run_for_symbol(_session, **kwargs):
        captured["source"] = kwargs["source"]
        return rr.RegimeRunResult(
            symbol=kwargs["symbol"],
            regime=Regime.SIDEWAYS,
            confidence=0.0,
            state_means={},
            n_obs=0,
            status="no-data",
        )

    monkeypatch.setattr(rr, "resolve_ohlcv_source", fake_resolve)
    monkeypatch.setattr(rr, "run_for_symbol", fake_run_for_symbol)

    await rr.run_for_watchlist(_WatchlistSession(["SPY"]))

    assert captured["source"] == "yfinance"  # heuristic fallback for a US ticker
