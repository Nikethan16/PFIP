"""Sentiment classification — FinBERT (news) + CryptoBERT (crypto social).

Lazy loads HuggingFace transformer pipelines on first call, caches models
under ``/root/.cache/huggingface`` (bind-mounted in docker-compose).

The service is queue-consumer friendly: ingesters push raw text + a
destination callback, the classifier batches input per call, and writes back
a ``SentimentResult`` with the fields the plan calls for — ``pos``, ``neg``,
``neu`` and a signed ``score`` in [-1, 1].

Fallback: if ``transformers`` / models fail to load for any reason we emit
a neutral result so upstream pipelines keep moving — the plan calls for this
explicitly ("fall back to neutral if load fails").
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from typing import Any, Iterable

log = logging.getLogger(__name__)


# Default model identifiers per plan Section 6.
_FINBERT_MODEL = "ProsusAI/finbert"
_CRYPTOBERT_MODEL = "ElKulako/cryptobert"
_HF_CACHE = os.environ.get("HF_HOME") or "/root/.cache/huggingface"


@dataclass(frozen=True)
class SentimentResult:
    """Sentiment classification output for one text.

    ``score`` collapses (pos, neg, neu) into a signed [-1, 1] scalar suitable
    for the ``news.sentiment`` column, with the rule ``pos - neg``.
    """

    pos: float
    neg: float
    neu: float
    score: float
    label: str
    model: str


def _neutral(model_id: str) -> SentimentResult:
    return SentimentResult(
        pos=0.0, neg=0.0, neu=1.0, score=0.0, label="neutral", model=model_id
    )


class SentimentService:
    """Batched sentiment classifier.

    Loads models lazily and caches them per-thread via the HuggingFace pipeline
    object. Call ``classify_news(texts)`` or ``classify_crypto(texts)``.
    """

    def __init__(
        self,
        news_model: str = _FINBERT_MODEL,
        crypto_model: str = _CRYPTOBERT_MODEL,
        cache_dir: str = _HF_CACHE,
        batch_size: int = 16,
    ) -> None:
        self.news_model = news_model
        self.crypto_model = crypto_model
        self.cache_dir = cache_dir
        self.batch_size = batch_size

        self._news_pipe: Any = None
        self._crypto_pipe: Any = None
        self._news_lock = threading.Lock()
        self._crypto_lock = threading.Lock()

        # Make cache dir if we can. Failing is non-fatal.
        try:
            os.makedirs(cache_dir, exist_ok=True)
        except Exception as exc:  # pragma: no cover
            log.warning("sentiment: could not create HF cache dir %s (%s)", cache_dir, exc)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def classify_news(self, texts: Iterable[str]) -> list[SentimentResult]:
        """Classify a batch of news texts using FinBERT."""
        return self._classify(list(texts), kind="news")

    def classify_crypto(self, texts: Iterable[str]) -> list[SentimentResult]:
        """Classify a batch of crypto social texts using CryptoBERT."""
        return self._classify(list(texts), kind="crypto")

    def classify(self, texts: Iterable[str], *, kind: str = "news") -> list[SentimentResult]:
        """Generic entry — ``kind`` ∈ {``news``, ``crypto``}."""
        return self._classify(list(texts), kind=kind)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _classify(self, texts: list[str], *, kind: str) -> list[SentimentResult]:
        if not texts:
            return []

        model_id = self.news_model if kind == "news" else self.crypto_model
        pipe = self._get_pipe(kind)
        if pipe is None:
            return [_neutral(model_id) for _ in texts]

        results: list[SentimentResult] = []
        for i in range(0, len(texts), self.batch_size):
            chunk = texts[i : i + self.batch_size]
            try:
                raw = pipe(chunk, top_k=None, truncation=True)
            except Exception as exc:
                log.warning("sentiment: pipeline call failed (%s); neutral fallback", exc)
                results.extend(_neutral(model_id) for _ in chunk)
                continue
            # HF may return either list[list[dict]] (top_k>1) or list[dict] (one per input).
            for item in raw:
                scores = _to_score_dict(item)
                pos = scores.get("positive", 0.0)
                neg = scores.get("negative", 0.0)
                neu = scores.get("neutral", max(0.0, 1.0 - (pos + neg)))
                total = pos + neg + neu
                if total > 0:
                    pos, neg, neu = pos / total, neg / total, neu / total
                label = max(
                    (("positive", pos), ("negative", neg), ("neutral", neu)),
                    key=lambda kv: kv[1],
                )[0]
                results.append(
                    SentimentResult(
                        pos=pos, neg=neg, neu=neu, score=pos - neg, label=label, model=model_id
                    )
                )
        return results

    def _get_pipe(self, kind: str) -> Any:
        """Lazy-load + cache a HF pipeline per kind."""
        if kind == "news":
            if self._news_pipe is not None:
                return self._news_pipe
            with self._news_lock:
                if self._news_pipe is None:
                    self._news_pipe = self._build_pipe(self.news_model)
            return self._news_pipe
        if kind == "crypto":
            if self._crypto_pipe is not None:
                return self._crypto_pipe
            with self._crypto_lock:
                if self._crypto_pipe is None:
                    self._crypto_pipe = self._build_pipe(self.crypto_model)
            return self._crypto_pipe
        raise ValueError(f"Unknown kind={kind}")

    def _build_pipe(self, model_id: str) -> Any:
        """Load a transformers pipeline. Returns ``None`` on failure (neutral fallback)."""
        try:  # pragma: no cover — external deps not guaranteed in test env
            from transformers import (  # type: ignore[import-not-found]
                AutoModelForSequenceClassification,
                AutoTokenizer,
                pipeline,
            )

            tokenizer = AutoTokenizer.from_pretrained(model_id, cache_dir=self.cache_dir)
            model = AutoModelForSequenceClassification.from_pretrained(
                model_id, cache_dir=self.cache_dir
            )
            return pipeline(
                task="text-classification",
                model=model,
                tokenizer=tokenizer,
                device=-1,  # CPU — GPU would need CUDA + --gpus flag
                batch_size=self.batch_size,
            )
        except Exception as exc:
            log.warning(
                "sentiment: failed to load %s (%s); will emit neutral results",
                model_id,
                exc,
            )
            return None


def _to_score_dict(item: Any) -> dict[str, float]:
    """Flatten a HF classifier response into ``{label_lower: score}``."""
    out: dict[str, float] = {}
    if isinstance(item, list):
        for x in item:
            if isinstance(x, dict) and "label" in x and "score" in x:
                out[str(x["label"]).lower()] = float(x["score"])
    elif isinstance(item, dict) and "label" in item and "score" in item:
        out[str(item["label"]).lower()] = float(item["score"])
    return out


# ---------------------------------------------------------------------------
# Module-level singleton (queue consumer uses this).
# ---------------------------------------------------------------------------

_service: SentimentService | None = None
_svc_lock = threading.Lock()


def get_sentiment_service() -> SentimentService:
    """Return the process-wide ``SentimentService`` singleton."""
    global _service
    if _service is None:
        with _svc_lock:
            if _service is None:
                _service = SentimentService()
    return _service
