"""Pure-logic tests for the Round-2 additions:

- Intent classifier (`pfip.agent.intent`).
- News attachment ranker (`pfip.signals.news_attach`).
- Fundamentals ratio helpers (`pfip.features.fundamentals_ratios`).
- Market-close renderer (`pfip.agent.market_close.render_markdown`).
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from pfip.agent.intent import Intent, classify_intent
from pfip.agent.market_close import (
    IndexMove,
    MarketCloseSummary,
    NewsHit,
    SignalCount,
    WatchlistMove,
    render_markdown,
)
from pfip.features.fundamentals_ratios import (
    Fundamentals,
    compute_all,
    debt_to_equity,
    fundamentals_from_dict,
    pe_ratio,
)
from pfip.signals.news_attach import (
    NewsForSignal,
    select_news_for_signal,
)

# ---------------------------------------------------------------------------
# Intent classifier
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("How much BTC do I hold?", Intent.DB_QUERY),
        ("show me my open positions", Intent.DB_QUERY),
        ("What was my P&L yesterday", Intent.DB_QUERY),
        ("list my journal entries", Intent.DB_QUERY),
        ("What does Wyckoff say about accumulation?", Intent.RAG_LOOKUP),
        ("what's the news on RELIANCE today", Intent.RAG_LOOKUP),
        ("Should I buy more ETH right now?", Intent.REASONING),
        ("explain your last signal", Intent.REASONING),
        ("why did NVDA gap up overnight", Intent.REASONING),
    ],
)
def test_intent_classifier_routing(text, expected):
    out = classify_intent(text)
    assert out.intent == expected, f"{text!r} → {out}"


def test_intent_classifier_empty_falls_back():
    out = classify_intent("")
    assert out.intent == Intent.REASONING
    assert out.confidence < 0.5


def test_intent_classifier_one_word_falls_back():
    out = classify_intent("Hello")
    assert out.intent == Intent.REASONING


def test_intent_classifier_no_match_falls_back():
    out = classify_intent("The weather is nice in May")
    assert out.intent == Intent.REASONING


# ---------------------------------------------------------------------------
# News attachment ranker
# ---------------------------------------------------------------------------


def _news(title: str, sentiment: float, impact: int, hours_ago: int = 1) -> NewsForSignal:
    return NewsForSignal(
        title=title,
        url=f"https://example.com/{title.replace(' ', '_')}",
        published_at=datetime.now(tz=timezone.utc),
        sentiment=sentiment,
        impact=impact,
    )


def test_buy_signal_picks_positive_sentiment_as_supporting():
    items = [
        _news("Bull A", sentiment=0.8, impact=90),
        _news("Bear A", sentiment=-0.7, impact=85),
        _news("Bull B", sentiment=0.5, impact=70),
    ]
    sup, opp = select_news_for_signal(items, direction="BUY")
    assert [n.title for n in sup] == ["Bull A", "Bull B"]
    assert [n.title for n in opp] == ["Bear A"]


def test_sell_signal_picks_negative_sentiment_as_supporting():
    items = [
        _news("Bull", sentiment=0.6, impact=80),
        _news("Bear High", sentiment=-0.8, impact=95),
        _news("Bear Low", sentiment=-0.4, impact=60),
    ]
    sup, opp = select_news_for_signal(items, direction="SELL")
    assert [n.title for n in sup] == ["Bear High", "Bear Low"]
    assert [n.title for n in opp] == ["Bull"]


def test_top_k_caps_lists():
    items = [_news(f"item_{i}", sentiment=0.5, impact=100 - i) for i in range(20)]
    sup, opp = select_news_for_signal(items, direction="BUY", top_support=3, top_oppose=2)
    assert len(sup) == 3
    assert len(opp) == 0  # everything is positive
    # Top-3 should be the highest-impact items.
    assert [n.title for n in sup] == ["item_0", "item_1", "item_2"]


def test_hold_signal_picks_neutral_as_supporting():
    items = [
        _news("Strong bull", sentiment=0.9, impact=90),
        _news("Neutral", sentiment=0.05, impact=50),
        _news("Strong bear", sentiment=-0.9, impact=80),
    ]
    sup, opp = select_news_for_signal(items, direction="HOLD")
    assert [n.title for n in sup] == ["Neutral"]
    assert sorted(n.title for n in opp) == ["Strong bear", "Strong bull"]


# ---------------------------------------------------------------------------
# Fundamentals ratios
# ---------------------------------------------------------------------------


def test_pe_ratio_basic():
    assert pe_ratio(Fundamentals(price=100.0, eps_ttm=5.0)) == pytest.approx(20.0)


def test_pe_ratio_none_on_zero_eps():
    assert pe_ratio(Fundamentals(price=100.0, eps_ttm=0)) is None


def test_pe_ratio_none_on_negative_eps():
    assert pe_ratio(Fundamentals(price=100.0, eps_ttm=-5.0)) is None


def test_pe_ratio_none_on_missing_price():
    assert pe_ratio(Fundamentals(price=None, eps_ttm=5.0)) is None


def test_debt_to_equity_basic():
    assert debt_to_equity(Fundamentals(total_debt=500.0, total_equity=1000.0)) == 0.5


def test_compute_all_returns_dict_with_known_keys():
    f = Fundamentals(
        price=100, eps_ttm=5, book_value_per_share=50, total_debt=200, total_equity=400
    )
    out = compute_all(f)
    assert "pe_ratio" in out
    assert "pb_ratio" in out
    assert "debt_to_equity" in out
    assert out["pe_ratio"] == pytest.approx(20.0)
    assert out["pb_ratio"] == pytest.approx(2.0)
    assert out["debt_to_equity"] == pytest.approx(0.5)


def test_fundamentals_from_dict_tolerates_missing_keys():
    f = fundamentals_from_dict({"price": 100, "eps_ttm": 5})
    assert f.price == 100
    assert f.eps_ttm == 5
    assert f.total_debt is None


# ---------------------------------------------------------------------------
# Market-close renderer
# ---------------------------------------------------------------------------


def test_market_close_render_contains_header():
    s = MarketCloseSummary(fy_date=date(2026, 5, 29))
    md = render_markdown(s)
    assert "Market close" in md
    assert "2026" in md


def test_market_close_render_indexes_table():
    s = MarketCloseSummary(
        fy_date=date(2026, 5, 29),
        indexes=[IndexMove(symbol="^NSEI", close=25000.0, change_pct=1.2)],
    )
    md = render_markdown(s)
    assert "^NSEI" in md
    assert "25,000.00" in md
    assert "+1.20%" in md


def test_market_close_render_no_breaches_label():
    s = MarketCloseSummary(fy_date=date(2026, 5, 29))
    md = render_markdown(s)
    assert "No breaches today" in md


def test_market_close_render_with_signals_and_news():
    s = MarketCloseSummary(
        fy_date=date(2026, 5, 29),
        watchlist_gainers=[WatchlistMove(symbol="BTC/USD", change_pct=3.5)],
        signal_counts=[SignalCount(regime="bull_trend", count=2)],
        top_news=[NewsHit(title="Big news", impact=88, url="https://example.com")],
    )
    md = render_markdown(s)
    assert "BTC/USD" in md
    assert "Top news by impact" in md
    assert "Big news" in md
    assert "New signals today" in md
