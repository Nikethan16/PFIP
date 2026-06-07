"""Tests for the news enrichment helpers.

Coverage:

- url_dedup_key normalizes tracking params + trailing slash.
- title_fuzzy_key stable under stop-word and order changes.
- dedup_articles drops both URL-dupes and near-title-dupes.
- heuristic sentiment direction is correct on canonical positive /
  negative sentences.
- entity extraction picks up tickers, crypto, central banks, sectors.
- impact_score returns 0–100 and weights keywords + sentiment.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from pfip.news.enrich import (
    Article,
    classify_sentiment,
    dedup_articles,
    extract_entities,
    impact_score,
    title_fuzzy_key,
    url_dedup_key,
)


# ---------------------------------------------------------------------------
# Dedup
# ---------------------------------------------------------------------------


def test_url_dedup_strips_query_and_fragment():
    a = url_dedup_key("https://example.com/news/abc?utm=foo#section")
    b = url_dedup_key("https://example.com/news/abc")
    assert a == b


def test_url_dedup_handles_trailing_slash():
    assert url_dedup_key("https://x.com/news/") == url_dedup_key("https://x.com/news")


def test_url_dedup_distinguishes_different_paths():
    assert url_dedup_key("https://x.com/a") != url_dedup_key("https://x.com/b")


def test_title_fuzzy_key_stable_under_reorder():
    """Same significant tokens in different order = same key."""
    a = title_fuzzy_key("Apple beats earnings expectations")
    b = title_fuzzy_key("Expectations beats earnings Apple")
    assert a == b


def test_title_fuzzy_key_ignores_stopwords():
    a = title_fuzzy_key("Apple beats earnings")
    b = title_fuzzy_key("Apple beats the earnings")
    assert a == b


def test_title_fuzzy_key_distinguishes_different_topics():
    a = title_fuzzy_key("Apple beats earnings")
    b = title_fuzzy_key("Tesla recalls SUVs")
    assert a != b


def test_dedup_articles_drops_url_duplicate():
    articles = [
        Article(url="https://x.com/1", title="First"),
        Article(url="https://x.com/1?utm=foo", title="First (republished)"),
    ]
    out = dedup_articles(articles)
    assert len(out) == 1


def test_dedup_articles_drops_title_near_duplicate():
    articles = [
        Article(url="https://a.com/x", title="Apple beats earnings"),
        Article(url="https://b.com/y", title="Apple beats the earnings"),
    ]
    out = dedup_articles(articles)
    assert len(out) == 1


def test_dedup_articles_keeps_distinct():
    articles = [
        Article(url="https://a.com/x", title="Apple beats earnings"),
        Article(url="https://b.com/y", title="Tesla recalls SUVs"),
    ]
    out = dedup_articles(articles)
    assert len(out) == 2


# ---------------------------------------------------------------------------
# Sentiment
# ---------------------------------------------------------------------------


def test_sentiment_positive_sentence():
    s = classify_sentiment("Apple surges to record high on strong earnings beat")
    assert s.label == "positive"
    assert s.score > 0


def test_sentiment_negative_sentence():
    s = classify_sentiment("Tesla plunges as profit miss sparks lawsuit")
    assert s.label == "negative"
    assert s.score < 0


def test_sentiment_neutral_sentence():
    s = classify_sentiment("Apple held its annual shareholder meeting today")
    # Neutral or borderline; assert score is near zero, regardless of label.
    assert -0.2 <= s.score <= 0.2


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------


def test_extract_ticker():
    ents = extract_entities("AAPL beats earnings")
    assert any(e.kind == "ticker" and e.text == "AAPL" for e in ents)


def test_extract_crypto_ticker():
    ents = extract_entities("BTC hits new high")
    assert any(e.kind == "crypto" and e.text == "BTC" for e in ents)


def test_extract_central_bank():
    ents = extract_entities("Fed signals rate hike at FOMC")
    kinds = {e.kind for e in ents}
    assert "central_bank" in kinds


def test_extract_sector():
    ents = extract_entities("Indian banking sector posts strong Q3")
    sectors = [e.text for e in ents if e.kind == "sector"]
    assert "bank" in sectors or "banking" in sectors


# ---------------------------------------------------------------------------
# Impact
# ---------------------------------------------------------------------------


def test_impact_score_in_range():
    art = Article(url="https://x.com/1", title="Hello world", body="")
    assert 0 <= impact_score(art) <= 100


def test_impact_score_high_for_loaded_headline():
    art = Article(
        url="https://x.com/1",
        title="AAPL hit by SEC investigation; earnings miss triggers fraud probe",
        body="The SEC filing reveals…",
        published_at=datetime.now(tz=timezone.utc),
    )
    score = impact_score(art)
    assert score >= 60


def test_impact_score_low_for_bland_old_headline():
    art = Article(
        url="https://x.com/1",
        title="Company holds annual meeting",
        body="",
        published_at=datetime.now(tz=timezone.utc) - timedelta(days=5),
    )
    score = impact_score(art)
    assert score < 30


def test_impact_score_recency_bonus():
    """Same article with recent vs old timestamp must get higher score when recent."""
    recent = Article(
        url="https://x.com/r",
        title="Apple unveils new product",
        body="",
        published_at=datetime.now(tz=timezone.utc),
    )
    old = Article(
        url="https://x.com/o",
        title="Apple unveils new product",
        body="",
        published_at=datetime.now(tz=timezone.utc) - timedelta(days=5),
    )
    assert impact_score(recent) > impact_score(old)
