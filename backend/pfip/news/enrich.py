"""News enrichment pipeline — dedup, sentiment, entities, impact.

This module is the lightweight middle layer between the raw ingest
adapters and the storage layer. It does *not* train models; it uses
either:

- The optional `transformers` pipeline for FinBERT/CryptoBERT sentiment,
  *if* installed; otherwise
- A deterministic, hand-rolled keyword scorer that's "good enough" for
  the dashboard and the news → signal join.

The same shape applies to entity extraction: spaCy if available,
regex-based fallback otherwise.

Public surface (all pure functions — no DB / network):

- :func:`url_dedup_key` — canonical hash of the URL.
- :func:`title_fuzzy_key` — locality-sensitive hash for near-duplicate titles.
- :func:`dedup_articles` — collapse a batch of (url, title, body) into uniques.
- :func:`classify_sentiment` — returns {label, score} per article.
- :func:`extract_entities` — list of (kind, text) tuples.
- :func:`impact_score` — 0–100 number combining vol-keywords, sentiment
  magnitude, entity importance, and recency.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

# ---------------------------------------------------------------------------
# Dedup
# ---------------------------------------------------------------------------


_URL_NORMALIZE = re.compile(r"[?#].*$")
_NON_ALNUM = re.compile(r"[^a-z0-9]")
_STOPWORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "of",
    "to",
    "in",
    "for",
    "on",
    "is",
    "with",
    "as",
    "by",
    "at",
    "this",
    "that",
    "from",
    "are",
    "was",
    "be",
    "it",
    "its",
}


def url_dedup_key(url: str) -> str:
    """SHA-256 of the URL with query/fragment stripped + lowercase.

    Yahoo/Moneycontrol et al. add tracking params; the canonical URL
    shouldn't depend on them.
    """
    u = (url or "").strip().lower()
    u = _URL_NORMALIZE.sub("", u)
    u = u.rstrip("/")
    return hashlib.sha256(u.encode("utf-8")).hexdigest()


def _title_token_set(title: str) -> set[str]:
    cleaned = _NON_ALNUM.sub(" ", (title or "").lower())
    tokens = {t for t in cleaned.split() if len(t) >= 3 and t not in _STOPWORDS}
    return tokens


def title_fuzzy_key(title: str) -> str:
    """Token-set hash that's stable under reordering and minor stop-word
    insertion/deletion. Two headlines hash to the same key when they
    share the same significant tokens regardless of order."""
    tokens = _title_token_set(title)
    if not tokens:
        return hashlib.sha256(b"").hexdigest()
    canonical = " ".join(sorted(tokens))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class Article:
    """Minimal article shape for the pipeline. Adapters convert their
    native shape to this before calling :func:`dedup_articles`."""

    url: str
    title: str
    body: str = ""
    published_at: datetime | None = None
    source: str = ""
    tags: list[str] = field(default_factory=list)


def dedup_articles(articles: Iterable[Article]) -> list[Article]:
    """Drop articles that share a URL hash *or* a title-fuzzy hash with
    an earlier article in the batch. First-seen wins."""
    seen_url: set[str] = set()
    seen_title: set[str] = set()
    out: list[Article] = []
    for a in articles:
        uk = url_dedup_key(a.url)
        tk = title_fuzzy_key(a.title)
        if uk in seen_url or tk in seen_title:
            continue
        seen_url.add(uk)
        seen_title.add(tk)
        out.append(a)
    return out


# ---------------------------------------------------------------------------
# Sentiment
# ---------------------------------------------------------------------------


_POSITIVE_WORDS = {
    "surge",
    "rally",
    "beat",
    "exceed",
    "soar",
    "jump",
    "gain",
    "rise",
    "growth",
    "profit",
    "upgrade",
    "bullish",
    "outperform",
    "record",
    "strong",
    "boost",
    "optimistic",
    "expansion",
    "rebound",
    "breakthrough",
    "approval",
    "high",
    "win",
    "wins",
}
_NEGATIVE_WORDS = {
    "plunge",
    "crash",
    "miss",
    "slump",
    "fall",
    "drop",
    "loss",
    "decline",
    "downgrade",
    "bearish",
    "warn",
    "warning",
    "investigation",
    "fraud",
    "lawsuit",
    "recall",
    "layoff",
    "cut",
    "weak",
    "low",
    "sue",
    "sues",
    "halt",
    "halted",
    "fail",
    "fails",
    "failure",
    "concern",
    "concerns",
}


def _heuristic_sentiment(text: str) -> tuple[str, float]:
    """Return (label, score in [-1,1]) using the word-bag heuristic."""
    tokens = _NON_ALNUM.sub(" ", (text or "").lower()).split()
    pos = sum(1 for t in tokens if t in _POSITIVE_WORDS)
    neg = sum(1 for t in tokens if t in _NEGATIVE_WORDS)
    if pos == 0 and neg == 0:
        return ("neutral", 0.0)
    score = (pos - neg) / max(1, pos + neg)
    if score > 0.1:
        return ("positive", score)
    if score < -0.1:
        return ("negative", score)
    return ("neutral", score)


@dataclass(slots=True)
class Sentiment:
    label: str  # "positive" / "neutral" / "negative"
    score: float  # [-1, 1]


def classify_sentiment(text: str) -> Sentiment:
    """Score a single text. Tries FinBERT lazily; falls back to heuristic."""
    try:
        # Optional dep — keep cold-start cheap.
        from transformers import pipeline  # type: ignore  # pragma: no cover

        clf = pipeline(  # pragma: no cover — optional path
            "sentiment-analysis",
            model="ProsusAI/finbert",
            top_k=1,
        )
        out = clf(text[:512])
        if isinstance(out, list) and out:
            inner = out[0][0] if isinstance(out[0], list) else out[0]
            label = inner["label"].lower()
            score = float(inner["score"])
            if label == "positive":
                return Sentiment("positive", score)
            if label == "negative":
                return Sentiment("negative", -score)
            return Sentiment("neutral", 0.0)
    except ImportError:
        pass
    except Exception:
        # transformers loaded but model unavailable / OOM — fall through.
        pass
    label, score = _heuristic_sentiment(text)
    return Sentiment(label=label, score=score)


# ---------------------------------------------------------------------------
# Entity extraction
# ---------------------------------------------------------------------------


# Crude ticker regex: 2-5 caps, optionally followed by .NS / .BO / .NSE / -USD.
_TICKER_RE = re.compile(r"\b([A-Z]{1,6})(?:\.(?:NS|BO|NSE|BSE)|-USD)?\b")
# Crypto ticker shortlist (uppercase already handled but we want to
# distinguish CRYPTO from EQUITY in the output).
_CRYPTO_TICKERS = {"BTC", "ETH", "SOL", "BNB", "USDT", "USDC", "ADA", "DOT", "XRP", "DOGE"}
# Central banks / common entities the user wants to track.
_CENTRAL_BANKS = {"fed", "fomc", "rbi", "ecb", "boj", "boe", "pboc", "scl"}
_SECTOR_KEYWORDS = {
    "bank",
    "banking",
    "tech",
    "energy",
    "metals",
    "pharma",
    "auto",
    "fmcg",
    "it",
    "telecom",
    "real estate",
    "crypto",
    "defi",
}


@dataclass(slots=True)
class Entity:
    kind: str  # "ticker" / "crypto" / "central_bank" / "sector"
    text: str


def extract_entities(text: str) -> list[Entity]:
    """Cheap regex-and-vocabulary extraction. Order-stable, deduped."""
    if not text:
        return []
    out: list[Entity] = []
    seen: set[tuple[str, str]] = set()

    for m in _TICKER_RE.finditer(text):
        tok = m.group(0)
        ticker = m.group(1)
        kind = "crypto" if ticker in _CRYPTO_TICKERS else "ticker"
        key = (kind, tok.upper())
        if key in seen:
            continue
        seen.add(key)
        out.append(Entity(kind=kind, text=tok))

    lower = text.lower()
    for cb in _CENTRAL_BANKS:
        if re.search(rf"\b{cb}\b", lower):
            key = ("central_bank", cb)
            if key not in seen:
                seen.add(key)
                out.append(Entity(kind="central_bank", text=cb.upper()))

    for sec in _SECTOR_KEYWORDS:
        if re.search(rf"\b{re.escape(sec)}\b", lower):
            key = ("sector", sec)
            if key not in seen:
                seen.add(key)
                out.append(Entity(kind="sector", text=sec))

    return out


# ---------------------------------------------------------------------------
# Impact score 0–100
# ---------------------------------------------------------------------------


_HIGH_IMPACT_KEYWORDS = {
    "earnings",
    "guidance",
    "outage",
    "halt",
    "delist",
    "delisted",
    "bankrupt",
    "merger",
    "acquisition",
    "ipo",
    "buyback",
    "stake",
    "stake-sale",
    "split",
    "dividend",
    "fomc",
    "rate hike",
    "rate cut",
    "recession",
    "default",
    "investigation",
    "fraud",
    "sec filing",
    "8-k",
    "10-k",
    "10-q",
    "sebi",
    "rbi policy",
    "hack",
    "exploit",
    "rug",
    "regulation",
    "ban",
}


def impact_score(article: Article, *, sentiment: Sentiment | None = None) -> int:
    """Combine signal-laden keywords, sentiment magnitude, entity count,
    and recency into a 0-100 integer.

    Weights (deliberately simple and inspectable):
        - 40 pts max for high-impact keyword density in title + body
        - 30 pts max for |sentiment|
        - 20 pts max for entity richness (more entities = more reach)
        - 10 pts max for recency (full 10 within 6h, 0 after 72h)
    """
    sentiment = sentiment or classify_sentiment(article.title + " " + (article.body or ""))
    full = (article.title + " " + (article.body or "")).lower()

    # Keyword score
    hits = sum(1 for kw in _HIGH_IMPACT_KEYWORDS if kw in full)
    kw_pts = min(40, hits * 8)

    # Sentiment magnitude
    sent_pts = int(round(abs(sentiment.score) * 30))

    # Entities
    n_ents = len(extract_entities(article.title + " " + (article.body or "")))
    ent_pts = min(20, n_ents * 4)

    # Recency
    recency_pts = 0
    if article.published_at is not None:
        now = datetime.now(tz=timezone.utc)
        ts = article.published_at
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_h = max(0.0, (now - ts).total_seconds() / 3600.0)
        if age_h <= 6:
            recency_pts = 10
        elif age_h <= 24:
            recency_pts = 6
        elif age_h <= 72:
            recency_pts = 2

    return min(100, kw_pts + sent_pts + ent_pts + recency_pts)


__all__ = [
    "Article",
    "Entity",
    "Sentiment",
    "classify_sentiment",
    "dedup_articles",
    "extract_entities",
    "impact_score",
    "title_fuzzy_key",
    "url_dedup_key",
]
