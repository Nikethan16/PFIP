# ML Signal-Layer Research — OSS Model Bake-Off

_Date: 2026-06-23. Author: autonomous build pass. Status: **research / recommendation** — no
production wiring. `FEATURE_ML_SIGNALS` stays **OFF** until the data-readiness gate is met._

## 0. Question

PFIP already ships a classical signal stack:

- **Directional signals** — walk-forward `LGBMBaselineModel` (`signals/lgbm_baseline.py`) with
  isotonic calibration, SHAP drivers, and a regime router (`signals/regime_router.py` +
  `auto_selector.py`).
- **Volatility** — `vol/garch.py` (GARCH workhorse).
- **Regime** — `regime/hmm.py`, `markov_switching.py`, and the new `change_point.py` (ruptures).

The question this doc answers: **should we add open-source foundation models — time-series
(Chronos / TimesFM / Moirai) or financial-NLP (FinBERT / FinLlama) — on top of these baselines,
and if so, where do they actually earn their keep given PFIP's constraints?**

## 1. PFIP's constraints (these decide everything)

| Constraint | Implication for model choice |
| --- | --- |
| **Single user, advisory-only** — no auto-execution, no latency race | Inference cost/throughput barely matter; **correctness + calibration + explainability** matter most. |
| **Modest infra** — Neon Postgres, optional Hetzner VPS, no GPU | Favor **CPU-friendly** models. A 7B LLM or GPU-only TSFM is a poor fit unless it clears a high bar. |
| **Thin data** — only ~10 assets currently clear ≥756 daily bars (5 NSE names + 5 crypto); US equities & several alts are shallow | **Zero-shot transfer** is the one place foundation models have a structural advantage over a per-asset GBM that needs history. |
| **Daily bars, direction @ t+3** is the signal target | Daily-return *direction* is near-random; no model family reliably beats a calibrated GBM here. The honest edge is in **volatility / scenario / regime**, not point-direction. |
| **Gate already exists** — `FEATURE_ML_SIGNALS=false` until ≥756 bars/asset | Any new model plugs in *behind the same gate*; this is a research track, not a launch. |

## 2. Evidence (2025–2026 literature)

**Time-series foundation models (TSFMs).** Chronos-2 (Oct 2025) is now the strongest pretrained
TSFM on the standard benchmarks (fev-bench, GIFT-Eval, Chronos Benchmark II), edging out
TimesFM-2.5 and Moirai-2.0; Chronos-Bolt is the efficient CPU-friendly variant (~hundreds× faster
than the original Chronos). **But** the finance-specific evidence is explicitly *nuanced*: surveys
and VaR studies find GARCH "remarkably robust" for volatility and find **no clear, consistent
out-of-sample win for TSFMs on daily financial returns**. Finance-native foundation models
(Kronos, FinCast) exist but are young and unproven on out-of-sample live trading. Conclusion:
**general-benchmark SOTA ≠ edge on daily Indian-equity/crypto returns.**

**Financial NLP.** FinBERT remains the pragmatic baseline for news/headline sentiment
(open, small, CPU-fine, ~0.71 macro-F1 fine-tuned). Fine-tuned 7B LLMs (FinLlama,
FinLLaMA-Instruct) beat FinBERT by ~8–10% accuracy — but at 7B-param hosting cost that a
single-user advisory app can't justify versus running our existing hosted LLM router for the rare
hard case.

## 3. Bake-off verdict

| Candidate | Task | Verdict for PFIP | Why |
| --- | --- | --- | --- |
| **LightGBM (incumbent)** | Directional signal | **Keep as champion** | Calibrated, explainable (SHAP → `drivers`), walk-forward honest, cheap. Best fit for the contract "no LLM generates a Signal." |
| **GARCH (incumbent)** | Volatility | **Keep** | Robust, interpretable, already wired. Literature still favors it. |
| **HMM / Markov / ruptures (incumbent)** | Regime | **Keep** | Drives the regime router; foundation models add nothing here. |
| **Chronos-Bolt** | Probabilistic multi-horizon forecast (vol cone / scenario prior) | **Adopt as a research track, gated** | CPU-friendly, zero-shot, quantile outputs. Value is **Monte-Carlo priors for the Goals/stress pages and a vol-cone overlay**, *not* directional signals. |
| TimesFM-2.5 / Moirai-2.0 | same as Chronos | **Skip (for now)** | No decisive edge over Chronos-Bolt; one TSFM dependency is enough. Re-evaluate if Chronos-Bolt underwhelms. |
| Kronos / FinCast (finance-native TSFM) | returns/vol | **Watch, don't adopt** | Promising but unproven OOS; revisit in 2 quarters. |
| **FinBERT** | News sentiment **feature** (not a signal) | **Adopt (small)** | Cheap, CPU-fine, turns `news` rows into a `news_sentiment` feature the GBM can consume. |
| FinLlama / FinLLaMA-Instruct (7B) | News sentiment | **Skip** | Hosting cost unjustified for single user; use the existing LLM router for the rare hard call. |

## 4. Recommended integration (all behind the existing gate)

1. **FinBERT → feature, not signal.** Add a `news_sentiment` feature computed from `news` rows
   and join it into the feature table. It feeds the existing GBM; it never emits a `Signal`
   directly (preserves the CONTRACTS.md rule). Lowest risk, clearest ROI. **Do first.**
2. **Chronos-Bolt → scenario/vol prior, not direction.** Use its quantile forecast to (a) seed the
   **Goals Monte-Carlo** drift/vol priors with a data-driven cone instead of a flat assumption, and
   (b) render a vol-cone overlay. Keep it advisory and clearly labelled "model-generated range."
   Add as an **optional dependency** so absence is a no-op (mirrors the existing `ruptures`/`lightgbm`
   soft-import pattern).
3. **Do NOT** route foundation models into directional `Signal` generation. The bar (beat a
   calibrated walk-forward GBM out-of-sample on daily direction) is not met by current evidence.
4. **Keep the data gate.** None of the above flips `FEATURE_ML_SIGNALS`. The gate stays until
   ≥756 bars/asset across the live universe (today: 10/20 symbols qualify — see
   `docs/SESSION_STATE` data audit). The cloud backfill deepening US equities is the unblock.

## 5. Validation protocol before anything ships

Reuse the existing discipline: **walk-forward only**, 21-day step / 21-day test / 5-day embargo,
CPCV cross-check, isotonic calibration, and report **Brier + ECE** (the calibration pipeline
already exists). A new model is adopted only if it beats the incumbent **on the same split** by a
margin that survives the embargo — no in-sample or leakage-prone comparisons.

## Sources

- [Chronos-2: From Univariate to Universal Forecasting](https://arxiv.org/pdf/2510.15821)
- [Moirai 2.0: When Less Is More for Time Series Forecasting](https://arxiv.org/html/2511.11698v1)
- [chronos-forecasting (Amazon Science, incl. Chronos-Bolt)](https://github.com/amazon-science/chronos-forecasting)
- [Time-Series Foundation Models in Finance: Pretraining Corpora, Architectures, Benchmarks, Risk-Aware Evaluation](https://dl.acm.org/doi/full/10.1145/3785706.3785728)
- [Time-Series Foundation AI Model for Value-at-Risk Forecasting](https://arxiv.org/html/2410.11773v7)
- [Time Series Foundation Models for Financial Markets: Kronos](https://jonathankinlay.com/2026/02/time-series-foundation-models-for-financial-markets-kronos-and-the-rise-of-pre-trained-market-models/)
- [FinCast: A Foundation Model for Financial Time-Series Forecasting](https://arxiv.org/html/2508.19609v1)
- [FinLlama: Financial Sentiment Classification for Algorithmic Trading](https://arxiv.org/abs/2403.12285)
- [Financial Sentiment Analysis: A Comparative Study of Fine-Tuned Deep Learning Models](https://www.mdpi.com/2227-7072/13/2/75)
