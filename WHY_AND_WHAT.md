# PFIP — Why We Need What We Need

A reference for understanding every external dependency, model, and data source. Read top to bottom; the reasoning compounds. Final section is a checklist to tick through with me.

---

## 0. The big picture

PFIP is fundamentally an **aggregator and analyzer**, not an originator. Markets, prices, news, fundamentals, your holdings — none of this is created inside the system. It all has to come in from somewhere. The system's job is:

1. **Pull** data continuously from many places.
2. **Store** it efficiently.
3. **Compute** features, signals, regime labels, calibration.
4. **Reason** about it (where LLMs come in — narrative, not decisions).
5. **Show** you what's happening (dashboard) and tell you when to look (alerts).
6. **Compute your tax liability** based on your actual holdings.

Every external API, every model, every infrastructure piece exists to serve one of those six steps. If something doesn't, it's bloat — call it out and we cut it.

---

## 0a. Operating principle — long-term reliability over short-term ease

Every choice in this doc favors **production-grade** over **demo-grade**. Concretely:

- **Reject Colab / hosted notebooks for production.** Sessions die after 12h, GPU access is throttled, no 24/7 ingest possible. Useful for prototyping; never the long-term home.
- **Reject no-code workflow tools (n8n, Make.com) for daily pipelines.** Great for hobbyists; brittle when the pipeline becomes critical. We use Prefect (Apache 2.0, code-versioned, real error handling).
- **Reject Telegram-only output.** Fine for alerts; insufficient as primary UI for portfolio + tax + calibration views.
- **Reject "we'll skip storage durability."** Backups, retention, restore drills are not optional.
- **Accept paid fallbacks where free tiers are unreliable.** Yfinance can break any time (it's unofficial); we document Tiingo (~$10/mo) and Polygon Stocks Starter (~$29/mo) as fallback paths for production-grade quoting if needed.

The blog "Insider's Guide to AI in Finance" was a good reference. Its *technical choices* (FinBERT, FinGPT, NASDAQ Data Link, FinQA) are largely sound. Its *infrastructure choices* (Colab, n8n, Telegram-only) trade reliability for setup speed — we don't.

---

## 0b. How data flows — historical, scheduled, where it runs

### Where it runs

**Everything runs on your machine, inside Docker containers.** No cloud, no remote servers, no data leaving your laptop except for the polite outbound requests to free APIs. When your laptop is off, ingest pauses; when you boot back up, Prefect catches up on missed scheduled runs.

If you later want 24/7 ingest without keeping the laptop on, that's the role of the optional ~$5/mo VPS (Decision D4 in Section 6).

### Two phases per data source

**Phase A — Historical backfill (one-time, when first enabled).** Pulls past data so charts and backtests have history. Triggered manually or by a Prefect "backfill" flow.

| Data | Backfill range | Storage location | Approx time |
|---|---|---|---|
| Crypto OHLCV (hourly) | 5 years | TimescaleDB `ohlcv` hypertable | ~5–10 min per asset |
| US equities (daily) | 5 years | Same table | ~5 sec per ticker |
| Indian equities (daily) | 5 years | Same table | ~10 sec per ticker |
| AMFI MF NAVs | Since 2006 | `mf_nav` table | ~10 min total |
| FX rates | 25 years | `fx_rates` table | ~2 min |
| Macro (FRED) | All available history | `macro_series` table | ~5 min |
| Fundamentals (SEC EDGAR) | Last 8 quarters per ticker | `fundamentals` table (with PIT `as_of_date`) | ~20 sec per ticker |
| News | Last 30 days | `news_items` + Qdrant embeddings | ~30 min total |

**Phase B — Ongoing scheduled pulls.** Prefect cron, runs while Docker is up.

### The schedule (revised — cadence per data type)

| Data | Cadence | Time (IST) | Why this cadence |
|---|---|---|---|
| **Crypto OHLCV hourly** | every hour at :05 | continuous | Crypto trades 24/7; daily would miss 23 hours. Coinbase free supports hourly trivially. |
| **News RSS feeds** | every 15 min | continuous | Earnings/macro events break in minutes. RSS has no formal rate limits. |
| **GDELT global firehose** | every 15 min | continuous | Matches GDELT's own update cadence. |
| **Reddit (PRAW)** | streaming | continuous | Push-based stream of new submissions/comments. |
| **Telegram (Telethon)** | streaming | continuous | Persistent connection to Telegram's servers. |
| **Bluesky firehose** | streaming (filtered) | continuous | AT Protocol jetstream. |
| **Self-custody wallet balances** | every 6 hours | 00:00 / 06:00 / 12:00 / 18:00 | Catches transfers without flooding the explorers. |
| **Indian equities EOD** | daily | 16:30 | After NSE/BSE market close + bhavcopy publish. |
| **FX rates (RBI/Frankfurter)** | daily | 17:30 | Both publishers update once daily. |
| **US equities EOD** | daily | 22:30 | After US market close (NYSE close = 01:30 IST next day; 22:30 captures previous-day close). |
| **AMFI mutual fund NAVs** | daily | 22:00 | After AMFI publishes evening NAVs. |
| **Macro (FRED, DBnomics)** | daily | 03:00 | FRED updates overnight US time. |
| **Fundamentals (SEC EDGAR)** | weekly | Sat 04:00 | Filings update on filing days; weekly captures all without flooding. |
| **Compute features (RSI/MACD/etc.)** | daily | 06:00 | After fresh OHLCV lands. |
| **HMM regime labels** | daily | 06:30 | After features computed. |
| **Morning brief** | daily | 07:00 | Before US market opens; main daily check-in. |
| **Market close summary** | daily | 17:30 | After Indian market closes; weekday only. |
| **Shadow portfolio reconcile** | daily | 23:30 | End-of-day rollup. |
| **Decision-journal post-mortem** | weekly | Sun 19:00 | End of week reflection. |
| **arXiv q-fin digest** | weekly | Sat 09:00 | Saturday morning paper-read. |
| **Calibration report (Brier/ECE)** | monthly | first Sat 10:00 | Catches model drift. |
| **Shadow vs actual rollup** | monthly | last Sun 19:00 | Honest performance check. |
| **Restore-from-backup drill** | quarterly | first Sat of Jan/Apr/Jul/Oct | DR readiness. |

### Cadence honesty notes

- **Indian intraday is genuinely not free.** NSE/BSE intraday tick data requires a broker API (Upstox or Angel One free; Zerodha Kite ₹2000/mo). Deferred for v1.
- **US intraday** is available free via Finnhub (60 req/min) and Alpaca paper account, but we don't poll it by default — daily decision-rhythm doesn't need it. Easy to enable later if you want intraday US signals.
- **Crypto hourly** is the right default; we can drop to 5-min or 1-min bars for active assets if you ever want HFT-style features. Storage is not a constraint.
- **News at 15 min** is aggressive enough to catch most material events while polite to RSS publishers. GDELT publishes every 15 min anyway, so matching it is natural.
- **Fundamentals weekly** is appropriate because companies file quarterly + ad-hoc 8-Ks; weekly catches all without flooding EDGAR.

---

## 1. Data categories — what we need and why

### 1.1 Market prices (OHLCV — open/high/low/close/volume)

**Why we need it:** can't answer any market question without knowing what prices have actually been. Backtests, signals, P&L, charts — all built on this.

**What we need:** daily prices for every asset on your watchlist + the indexes you track + everything you hold. Intraday optional, deferred for v1.

**Where we get it from:**
| Asset class | Source | Cost | Notes |
|---|---|---|---|
| Crypto | **Coinbase** (via ccxt) | Free, no key | Primary. Public exchanges expose OHLCV without auth. |
| Crypto | **Kraken**, **Bybit**, **OKX** (via ccxt) | Free, no key | Backups. If Coinbase rate-limits, fall over to these. |
| US equities | **yfinance** | Free, no key | Ticker e.g. AAPL, SPY. Unofficial Yahoo Finance scraper, but stable enough for personal use. |
| US equities | **Stooq** | Free, no key | Backup + retains delisted tickers (important for honest backtests). |
| Indian equities | **jugaad-data + NSE/BSE bhavcopy** | Free, no key | Daily bhavcopy is the official end-of-day download from NSE/BSE. jugaad-data wraps the URLs cleanly. |
| Indian mutual funds | **AMFI** (`amfiindia.com/spages/NAVAll.txt`) | Free, no key | The canonical source — every Indian mutual fund's NAV, daily. |
| FX | **Frankfurter** (`frankfurter.dev`) | Free, no key | ECB's reference rates wrapped in a clean API. |
| FX (USD/INR specifically) | **RBI reference rates page** | Free, no key, scraped | RBI is the authoritative source for INR. Tax computations need RBI's daily rate, not yfinance's quote. |
| Commodities | **yfinance futures tickers** (GC=F, SI=F, CL=F) | Free, no key | Gold, silver, oil futures. |
| Commodities (gold/silver) | **LBMA fixes** | Free | Authoritative gold/silver "fix" prices used by jewellers and central banks. |
| Commodities (US energy) | **EIA** | Free key | Government dataset for oil/gas/refining. |
| Commodities + global bonds + alt data | **NASDAQ Data Link** (formerly Quandl) | Free key | Free commodity futures, bond yields for 40+ countries, UN Comtrade trade-flow data. Gap-filler vs the rest of our stack. **Added after blog review.** |
| US equities (paid fallback) | **Tiingo** | ~$10/mo paid | Reliable EOD if yfinance breaks. Documented as long-term fallback. |
| US equities (paid fallback) | **Polygon Stocks Starter** | ~$29/mo paid | Real intraday + officially licensed. Document as fallback when free tier limits bite. |

**Caveat on yfinance:** it's an unofficial Yahoo Finance scraper, not a paid licensed API. Yahoo can change pages and break it any time. Acceptable for personal-use research; for any production-grade output we depend on, the paid fallback paths above must be wired in (currently documented, not yet integrated).

### 1.2 Fundamentals (P/E, revenue, debt, balance sheet)

**Why we need it:** ML signals trained only on price are weaker than ones that also see whether the company is actually profitable. Tax module also needs fundamentals to classify hybrid mutual funds.

**Where we get it from:**
| What | Source | Cost |
|---|---|---|
| US fundamentals (10-K, 10-Q, 8-K filings) | **SEC EDGAR** | Free, no key (just User-Agent header) |
| Indian fundamentals (P/E, revenue, ratios, 10y history) | **Screener.in** (scraped politely) | Free, personal use |
| Earnings calendar (US) | **Finnhub** | Free key |
| Indian corporate announcements | **NSE / BSE corporate-announcements feeds** | Free, no key |
| Mutual fund category, AUM, expense ratio | **AMFI** + **Moneycontrol MF section** | Free |

### 1.3 On-chain data (crypto-specific)

**Why we need it:** crypto prices alone don't tell the story. Knowing exchange reserves, miner behavior, whale movements, DeFi TVL is what separates retail charting from real signal.

**Where we get it from:**
| What | Source | Cost |
|---|---|---|
| BTC fundamentals (hash rate, mempool, fees) | **blockchain.info** + **mempool.space** | Free, no key |
| MVRV, exchange netflow, miner revenue | **Glassnode free tier** | Free key (limited metrics) |
| TVL, DeFi yields, stablecoin flows | **DefiLlama** | Free, no key |
| ~30 daily network metrics | **CoinMetrics Community** | Free, no key |
| Funding rate, OI, long/short, liquidations | **Coinglass free tier** | Free key |
| BTC/ETH/SOL options vol surface | **Deribit public** | Free, no key |
| Self-custody balance tracking | **mempool.space** (BTC), **Etherscan** (ETH), **Solscan** (SOL) | Free; ETH/SOL want a free key |

### 1.4 News (the "why" behind market moves)

**Why we need it:** prices change because something happened. The agent can't say "BTC dropped because the Fed hiked rates" without ingesting that news. News also feeds sentiment models for the signal layer.

**Where we get it from:**
| Source | What it gives us | Cost |
|---|---|---|
| **GDELT** | Global news firehose, every 15 min, with entity + tone tagging | Free, no key. Underused. |
| **Google News RSS per-query** | Per-ticker headlines | Free, no key |
| **Moneycontrol RSS, ET Markets RSS, LiveMint RSS, Business Standard RSS** | Indian markets news | Free, no key |
| **Yahoo per-ticker RSS** | US per-stock news | Free, no key |
| **CoinDesk, CoinTelegraph, Decrypt, The Block RSS** | Crypto news | Free, no key |
| **CryptoPanic free** | Crypto news aggregator | Free key |
| **MarketWatch RSS** | US markets headlines | Free, no key |
| **SEC 8-K RSS** | Real-time material US corporate filings (acquisitions, leadership changes, earnings) | Free, no key. Authoritative — not a news source, the source itself. |

### 1.5 Social signal (retail mood)

**Why we need it:** retail sentiment leads in crypto and small-caps. When everyone on Reddit is screaming about a stock, the move often follows.

**Where we get it from:**
| Source | Auth | What |
|---|---|---|
| **Reddit (PRAW)** — r/wallstreetbets, r/stocks, r/IndianStockMarket, r/IndiaInvestments, r/CryptoCurrency, r/CryptoMarkets | Free OAuth | Live stream of new posts/comments |
| **Telegram (Telethon)** — ~15 curated public channels (Whale Alert, Wu Blockchain, ET Markets, StockEdge, etc.) | Free dev API + dedicated phone number | Real-time alerts and curated commentary |
| **Bluesky firehose** (filtered by handle/keyword) | No key needed | X/Twitter replacement; finance community is growing here |
| **Farcaster** (via Neynar SDK) | Free key | Crypto-native social; strongest signal for crypto |
| **arXiv q-fin** | No key | Quantitative finance research papers — high signal, low noise |

### 1.6 Macro context (the regime)

**Why we need it:** a stock can be great fundamentally but get crushed in a recession. Without macro, we'd miss the difference between bull market and bear market. Affects regime detection + position sizing.

**Where we get it from:**
| Source | What | Auth |
|---|---|---|
| **FRED** (St. Louis Fed) | 800k+ US series: rates, CPI, VIX, DXY, yields | Free key |
| **DBnomics** | Aggregator for IMF, Eurostat, RBI data | No key |
| **World Bank** | Annual indicators (GDP, debt, etc.) | No key |
| **MOSPI** | India CPI, IIP, GDP | No key, scraped |
| **RBI** | Indian monetary policy, banking stats | No key, scraped |
| **Polymarket + Kalshi** | Prediction-market prices for Fed paths, recession odds, geopolitics | No key |

### 1.7 Personal holdings (your portfolio)

**Why we need it:** the entire portfolio/risk/tax layer is meaningless without knowing what you actually own.

**Where we get it from:** **You upload CSV exports.** No APIs.
- Indian equities/MF: Zerodha, ICICIdirect, Groww
- US stocks (Indian residents): INDmoney, Vested
- Indian crypto: WazirX, CoinDCX
- International crypto: Binance, Coinbase, Kraken

**Why no APIs:** for your own safety. PFIP only ever reads. We never connect to a broker with write access — that's how people get hacked or accidentally trade. You manually export, you manually upload.

### 1.8 Calendar events (when things will happen)

**Why we need it:** suppress signals during high-uncertainty windows (earnings, Fed meetings, RBI policy). Schedule the morning brief to hit before market open.

**Where we get it from:**
| Source | What | Auth |
|---|---|---|
| **Finnhub** | Earnings calendar + economic events | Free key |
| **FRED Releases** | US official release schedule | Free key |
| **RBI press releases** | India MPC, regulatory | No key |

---

## 2. Why we need LLMs (and what they don't do)

### 2.1 What an LLM is, in plain terms

A Large Language Model is a model that reads and writes natural language. We don't use it to predict prices. We use it for tasks that fundamentally need *reading* and *writing*.

### 2.2 The 6 specific things LLMs do in PFIP

**1. Read news articles and summarize what matters.**
Hundreds of news items hit the system per day. We can't read them all. The LLM summarizes the top 3–5 per asset, surfacing what's likely to actually move price.

**2. Answer natural-language questions about your portfolio.**
You ask "what's my exposure to IT sector?" or "which holdings are near stop-loss?" — instead of writing SQL, you type the question. The LLM converts it to a query, gets the answer, returns it in plain English.

**3. Generate the daily morning brief.**
The DB has all the numbers (overnight moves, news, regime, watchlist deltas). The LLM stitches them into readable prose. The numbers are real; the LLM just writes the connecting sentences.

**4. Draft post-mortems when you close a position.**
Pulls the entry signal, news at entry, news at exit, calibration of the model that suggested the trade. Drafts a structured "here's what happened and why" you then edit and approve. Without this, post-mortems get skipped.

**5. Run RAG ("Retrieval Augmented Generation") over the knowledge base of trading books.**
You ask "what would Lefèvre say about this setup?" — the LLM finds the relevant passages in the books we've ingested (semantic search via embeddings), pulls them in, and answers grounded in those quotes with citations.

**6. Re-formulate and entity-link news for downstream signals.**
Convert messy headlines into structured tags (which company, which sector, what kind of event). Feeds the news-conditioned signal layer.

### 2.3 What LLMs DO NOT do

- **They do not pick BUY/SELL.** That's the ML signal layer (LightGBM, etc.). LLMs hallucinate; we never trust them with the trade decision. This is architecturally enforced.
- **They do not generate prices or forecasts directly.** Time-series models (Chronos, TTM, etc.) handle that — and even those are advisory.
- **They do not handle tax math.** That's a deterministic rule engine. Tax law has no room for "the LLM thinks 30%."

### 2.4 Specialized small models (not LLMs, but worth grouping here)

| Use case | Model | Why |
|---|---|---|
| Classify news/article tone (pos/neg/neu) | **ProsusAI/finbert** | 110M params, specialized for financial text, runs on CPU |
| Classify crypto-social tone | **ElKulako/cryptobert** | Trained on crypto Twitter/Reddit, catches slang FinBERT misses |
| Detect market regime (bull/bear/sideways/high-vol) | **HMM** via hmmlearn | Lightweight statistical model on returns |
| Predict 3-day price direction | **LightGBM** classifier on technical features | Boosted trees beat foundation models on financial returns most of the time |
| (Optional) Volume / volatility forecasting | **TTM-r2 / Chronos / TimesFM** | Foundation time-series models — useful for volatility, often *not* better for returns |

---

## 3. Why each infrastructure piece

### 3.1 TimescaleDB (database)

**Why:** we're storing millions of OHLCV rows + features + holdings + tax events. A normal DB would slow to a crawl on time-series queries. TimescaleDB is Postgres with a time-series extension that makes "show me all of BTC's daily candles for the last 5 years" return in milliseconds.

**Alternatives:** plain Postgres + careful indexing (works at small scale, slows at large), DuckDB (analytics-first but in-process, no shared DB), ClickHouse (overkill for solo).

### 3.2 Qdrant (vector database)

**Why:** to answer "what books say something similar to this market situation," we need semantic search over book text. That requires storing text embeddings (each chunk → 768-dim vector) and finding nearest neighbors fast. Qdrant does this.

**Alternatives:** Chroma (lighter), Weaviate, FAISS (in-process, no server), pgvector (Qdrant features built into Postgres — viable swap if you want fewer services).

### 3.3 Redis (cache + queue)

**Why:** when the news pipeline classifies sentiment, it pushes onto a queue. The signal layer reads from another queue. Redis is the standard for this. Also caches "current regime" / "latest BTC price" so the dashboard doesn't hit the DB on every render.

**Alternatives:** Valkey (a Redis fork after the license change in 2024), in-process Python queues (works but loses durability across restarts).

### 3.4 Prefect (orchestration)

**Why:** something has to run "ingest BTC daily at 00:05 UTC, retry 3 times if it fails, alert me if it's failed for 3 hours straight." Prefect handles all of that. Without orchestration, your Sunday-night ingest job dies on Tuesday and you don't notice for a week.

**Alternatives:** Airflow (heavier, more mature), Dagster (newer, slicker), plain cron (works but fragile).

### 3.5 MLflow (model registry)

**Why:** when a signal fires, we need to know which model + which version produced it. Six months later, the calibration job will say "model X v3 has drifted." MLflow is the registry that tracks every training run, every metric, every artifact.

**Alternatives:** Weights & Biases (cloud, free tier), pure file-system + git tags (works at solo scale, less queryable).

### 3.6 Ollama (local LLM runtime)

**Why:** running Mistral-7B or Llama-3 locally on your machine. Free per-token cost, no data leaves your laptop, no rate limits. You pay in RAM and a few GB of disk.

**Alternatives:** llama.cpp directly (lower-level, more control), LM Studio (GUI app), cloud APIs like Groq/OpenAI/Anthropic (faster, but data leaves your machine + ongoing cost).

### 3.7 Sentry + Uptime Kuma (observability)

**Why:** when the BTC ingest crashes at 3 AM, you want to know in the morning. Sentry catches exceptions; Uptime Kuma watches each service is responding.

**Alternatives:** plain log files (works, less visible), self-hosted Grafana (heavier).

### 3.8 Next.js + FastAPI (the app itself)

**Why:**
- **Next.js** for the UI — modern React framework, server-rendered for fast page loads, mobile-responsive out of the box, type-safe with TypeScript.
- **FastAPI** for the backend API — fastest Python web framework with automatic OpenAPI docs and Pydantic validation.

**Alternatives:** Streamlit (faster to build but UI quality is limited — you flagged this earlier), Flask + plain HTML (simpler but more code).

---

## 4. Current choices vs. potential upgrades

### 4.1 LLM (chat agent / morning brief / post-mortems) — **UNDECIDED**

**Honest framing:** the LLM choice has not been benchmarked yet. The current default of Mistral-7B-Instruct was a reasonable starting placeholder, not a researched winner. Long-term reliability requires picking based on real evaluation, not vibes or blog hype.

**Candidates to evaluate (with FinQA + FinanceBench + custom finance-reasoning eval):**

| Candidate | Why it might win | Why it might lose |
|---|---|---|
| **Mistral-7B-Instruct** (current placeholder) | Apache 2.0, ~5 GB RAM, well-supported via Ollama | Generic; no finance-specific training |
| **FinGPT** (LoRA on Llama-2 / ChatGLM) | Pre-tuned on financial data, sentiment + Q&A finance-aware | Older base models (Llama-2 ≈ 2023); smaller community in 2026 |
| **Llama-3.1-8B-Instruct** + custom LoRA we train | Newer base, better reasoning, we control fine-tuning data | Need ~$50–200 of one-time GPU time to train the LoRA |
| **Qwen-2.5-7B-Instruct** | Strong math + financial reasoning out of box; recent (late 2024) | Chinese-origin (acceptable for solo use); less English-tuned |
| **DeepSeek-R1-Distill-Qwen-7B** | Chain-of-thought reasoning baked in — best for "explain why" tasks | Slower (more thinking tokens); newer, less battle-tested |
| **Groq cloud** (Llama-3.3-70B, free tier) | Way more capable; 10x faster than local | Data leaves your machine; rate-limited; requires internet |

**Decision plan:** pending Task #1 — actual benchmark run across all six on FinQA + FinanceBench + custom eval. Output: a comparison doc with numbers, you pick. Until then: Mistral stays as the default placeholder; nothing about the architecture depends on the specific LLM.

### 4.2 Embeddings (knowledge base + news search)

| Currently | **nomic-embed-text** (Ollama, local, ~1 GB RAM) |
| Why | Pure-Python access via Ollama, decent retrieval quality. |
| Upgrade options | |

| Alternative | Pros | Cons |
|---|---|---|
| **BGE-M3** (BAAI) | #1 on MTEB benchmark, multilingual (helpful for Hindi news) | Larger (~2 GB RAM); slightly more setup |
| **GTE-large** (Alibaba) | Strong English retrieval | English-only |
| **e5-mistral-7b** | Best quality | 5 GB RAM extra; heavy |

**Considerations:** retrieval quality directly affects how well the agent finds relevant book passages. BGE-M3 is the cleanest upgrade.

### 4.3 Sentiment

| News classifier | **ProsusAI/finbert** | Default since 2019, well-understood |
| Crypto social classifier | **ElKulako/cryptobert** | Best free option for crypto Twitter/Reddit |

**Upgrade considerations:**
- **finbert-tone (yiyanghkust)** is a slightly different model trained on earnings call transcripts — better for that domain.
- **DeBERTa-v3-finance variants** are newer, sometimes higher accuracy, less battle-tested.

For v1, ProsusAI + ElKulako is fine. Revisit when you have data showing one of them is misclassifying.

### 4.4 ML signal models

| Primary | **LightGBM** (gradient boosted trees) on 5 features (RSI, MACD, ATR, 7d return, 30d vol) |
| Why | Industry standard; finance returns have low signal-to-noise where boosted trees still win over deep learning. |

**Upgrade considerations:**
- **XGBoost** is a near-twin; some prefer its regularization. Trivial to add as ensemble member.
- **CatBoost** handles categorical features (regime, day-of-week) natively without leakage.
- **TTM / Chronos / TimesFM / Moirai** (foundation models) — coded in but not enabled by default. They underperform LightGBM on raw returns; useful for vol/volume forecasting.

### 4.5 Regime detection

| Currently | **HMM** (Hidden Markov Model, 3-state) via hmmlearn |
| Why | Lightweight statistical model. Trained on 3 years of returns. Outputs bull/bear/sideways/high-vol labels. |

**Upgrade considerations:**
- **GARCH models** for volatility regimes specifically.
- **Larger HMMs (4-5 states)** if you want finer distinctions (accumulation, distribution).
- **Foundation models** for "regime detection" — generally overkill at solo scale.

### 4.6 Backtesting

| Currently | **vectorbt OSS** (numpy-based, fast) |
| Why | Vectorized walk-forward + Monte Carlo at speed. |

**Upgrade considerations:**
- **QuantConnect LEAN** — institutional-grade engine, much heavier. Adopt if you outgrow vectorbt.
- **backtrader** — older, GPL-licensed. Avoid if you want to go commercial later.

### 4.7 Evaluation framework — multi-benchmark, not single

**Why we need it:** "the LLM seems to give good answers" is not evidence. Production systems need quantitative, reproducible benchmarks that catch drift over time. The v0.5 plan only specified RAGAS (retrieval quality) — that's necessary but insufficient for finance.

**The benchmark stack:**

| Benchmark | What it tests | Why we need it |
|---|---|---|
| **FinQA** (czyssrs/FinQA) | Multi-step numerical reasoning over real financial filings | Can the LLM actually do math over 10-K tables? Most general LLMs fail this. |
| **FinanceBench** (PatronusAI) | 10,231 questions over real 10-K/10-Q/8-K filings; tests retrieval + reasoning end-to-end | Tests the whole RAG pipeline, not just the LLM in isolation |
| **RAGAS** | Retrieval relevance, faithfulness, answer relevance | Catches when the agent retrieves wrong passages or hallucinates beyond them |
| **Custom finance-reasoning eval** (50–100 hand-built Q/A pairs over our actual data) | Domain-specific to *our* portfolio, *our* tax module, *our* watchlist | Catches model drift on the specific things we care about |

**Schedule:** all four run monthly per registered model. Results stored in MLflow. ECE thresholds + benchmark thresholds gate model promotion.

**This is a real correction from blog learnings.** The blog highlighted FinQA — they were right. The doc previously didn't include it.

---

## 5. Tech requirements — every library, tool, and service in use

This is the comprehensive inventory of what's installed and running. If a tool isn't listed here and you see it in the repo, that's a bug — flag it.

### 5.1 Backend — Python

| Library | Version | Purpose | License |
|---|---|---|---|
| **fastapi** | 0.111 | HTTP API framework | MIT |
| **uvicorn** | 0.30 | ASGI server | BSD |
| **pydantic** | 2.7 | Typed contracts (signals, holdings, etc.) | MIT |
| **pydantic-settings** | 2.3 | .env loader | MIT |
| **bcrypt + passlib + pyjwt** | — | Password hash + JWT auth | MIT/Apache |
| **sqlalchemy** | 2.0 (async) | ORM for TimescaleDB | MIT |
| **alembic** | 1.13 | DB migrations | MIT |
| **psycopg + asyncpg** | 3.2 / 0.29 | Postgres drivers | LGPL/Apache |
| **pandas + numpy** | 2.2 / 1.26 | Data manipulation | BSD |
| **ta** (replacing pandas-ta) | 0.11 | Technical indicators (RSI, MACD, ATR, etc.) | MIT |
| **pandera** | 0.19 | DataFrame schema validation at ingest | MIT |
| **scikit-learn** | 1.5 | Meta-learner, Isolation Forest, calibration metrics | BSD |
| **lightgbm** | 4.4 | Primary signal model (boosted trees) | MIT |
| **xgboost + catboost** | 2.1 / 1.2 | Ensemble alternatives | Apache |
| **hmmlearn** | 0.3 | HMM regime detection | BSD |
| **shap** | 0.45 | Per-prediction feature importance for signal explanations | MIT |
| **optuna** | 3.6 | Hyperparameter search | MIT |
| **statsmodels** | 0.14 | Classical stats baselines (ARIMA, GARCH if needed) | BSD |
| **mlflow** | 2.14 | Experiment tracking + model registry | Apache |
| **vectorbt** (optional) | 0.26 | Vectorized backtesting (skipped on Windows; numpy fallback works) | Apache |
| **prefect** | 2.19 | Pipeline orchestration | Apache |
| **ccxt** | 4.3 | Crypto exchange unified client (Coinbase, Kraken, Bybit, OKX) | MIT |
| **yfinance** | 0.2 | Unofficial Yahoo Finance — US + Indian EOD | Apache |
| **pandas-datareader** | 0.10 | Stooq, FRED helpers | BSD |
| **fredapi** | 0.5 | FRED macro | BSD |
| **jugaad-data + nsepython** | — | Indian NSE/BSE OHLCV + F&O | MIT |
| **etherscan-python** | 2.1 | ETH self-custody balance reads | MIT |
| **feedparser** | 6.0 | RSS ingest | BSD |
| **praw** | 7.7 | Reddit | BSD |
| **telethon** | 1.36 | Telegram public-channel reader | MIT |
| **atproto** | ≥0.0.55 | Bluesky AT Protocol client | MIT |
| **arxiv** | 2.1 | arXiv q-fin paper ingest | MIT |
| **selectolax + beautifulsoup4 + lxml** | — | HTML scraping for Screener.in, RBI, etc. | MIT/MIT/BSD |
| **httpx** | 0.27 | Async HTTP client across all ingest adapters | BSD |
| **tenacity** | 8.5 | Retry decorator on flaky external calls | Apache |
| **qdrant-client** | 1.9 | Vector DB client (KB + news embeddings) | Apache |
| **pypdf + ebooklib + langchain-text-splitters** | — | KB ingest pipeline (PDF → chunks → embed) | BSD/AGPL/MIT |
| **redis** | 5.0 | Cache + pub/sub | MIT |
| **loguru** | 0.7 | Structured logging | MIT |
| **sentry-sdk[fastapi]** | 2.7 | Exception capture | MIT |
| **reportlab** | 4.2 | Tax module PDF generation | BSD |
| **orjson** | 3.10 | Fast JSON | Apache |

### 5.2 Frontend — TypeScript / Next.js

| Library | Purpose |
|---|---|
| **next** 14 | Framework (App Router, server components) |
| **react** 18 + **typescript** 5 | UI + types |
| **tailwindcss** 3 + **postcss** + **autoprefixer** | Styling |
| **shadcn/ui** components | Accessible primitives (button, dialog, table, etc.) |
| **@tremor/react** | Dashboard primitives (KPI cards, donut, area charts) |
| **recharts** | Custom charts (candle chart, reliability diagram) |
| **@tanstack/react-query** v5 | Server-state caching + hooks |
| **zod** | Runtime contract validation matching Pydantic |
| **next-auth** v4 | Single-user JWT session |
| **react-hook-form** | Pre-trade checklist + post-mortem forms |
| **react-markdown + remark-gfm + rehype-highlight** | Morning brief + chat message rendering |
| **react-dropzone** | CSV upload zones in tax page |
| **cmdk** | Cmd+K command palette |
| **zustand** | Lightweight client state (network status, command palette open) |
| **date-fns** | IST formatting |
| **sonner** | Toast notifications |
| **lucide-react** | Icons |

### 5.3 LLM / agent layer

| Tool | Purpose | Status |
|---|---|---|
| **Ollama** (local LLM runtime) | Hosts whichever LLM we pick — no API cost | Running |
| **Mistral-7B-Instruct** | Current placeholder LLM | Default; pending benchmark research |
| **nomic-embed-text** (via Ollama) | Local embeddings for KB + news | Running |
| **LangGraph** (LangChain) | Agent orchestration: classify → retrieve → reason → cite | Wired in |
| **LangChain core** | RAG plumbing | — |
| **LlamaIndex** | KB ingestion + chunking | — |
| **RAGAS** | Retrieval-quality benchmark | Wired |
| **FinQA + FinanceBench** | Finance-reasoning benchmarks | **To wire (Task #2)** |
| **LangSmith** (free tier) | LLM call tracing for debugging | Optional |
| **Groq** (free tier, cloud) | Fallback when local Ollama too slow | Optional |
| **transformers + huggingface-hub** | Local sentiment classifiers (FinBERT, CryptoBERT) | When pulled |
| **ProsusAI/finbert** | Financial news sentiment | Default |
| **ElKulako/cryptobert** | Crypto-social sentiment | Default |

### 5.4 Infrastructure / services (Docker)

| Service | Image | Purpose |
|---|---|---|
| **TimescaleDB** | timescale/timescaledb:2.15-pg16 | Time-series + relational DB |
| **Redis** | redis:7.2-alpine | Cache + pub/sub |
| **Qdrant** | qdrant/qdrant:v1.9.3 | Vector DB |
| **Prefect** | prefecthq/prefect:2.19-python3.12 | Pipeline orchestration UI + API |
| **MLflow** | ghcr.io/mlflow/mlflow:v2.14.0 | Experiment + model registry |
| **Ollama** | ollama/ollama:latest | Local LLM runtime |
| **Uptime Kuma** | louislam/uptime-kuma:1 | Service uptime monitoring |
| **Backend** | built from /backend/Dockerfile | FastAPI app |
| **Frontend** | built from /frontend/Dockerfile | Next.js app |

### 5.5 Dev tooling + ops

| Tool | Purpose |
|---|---|
| **Docker Desktop** | Container runtime on your machine |
| **Node.js 20 LTS + pnpm** | Frontend build |
| **Python 3.12 + uv** | Backend dependency management |
| **Git** | Version control |
| **PowerShell 5.1+** | All scripts work on this minimum |
| **pytest + hypothesis** | Backend tests (unit + property-based) |
| **ruff + black + mypy** | Backend linting/formatting/types |
| **eslint + prettier** | Frontend linting/formatting |
| **GitHub Actions** | CI on PR (lint + test + compose-smoke) |

### 5.6 External services (not local)

| Service | Cost | Why |
|---|---|---|
| **Sentry** (free tier) | Free | Catches uncaught exceptions across backend + frontend |
| **LangSmith** (free tier) | Free | Debug LLM call traces |
| **Hetzner ARM VPS** (later, optional) | ~$5/mo | Read-only secondary ingest + backup target |
| **Cloud backup** (Backblaze B2 or rclone-to-Drive) | ~$5–10/mo | Off-site backup destination |
| **Tiingo paid** (if yfinance breaks) | ~$10/mo | Production fallback for US EOD |
| **Polygon Stocks Starter** (optional) | ~$29/mo | If we need licensed real-time US stock data |
| **Glassnode Advanced** (Stage 4+, optional) | ~$30/mo | Deeper crypto on-chain when free tier insufficient |

---

## 6. Inputs you need to provide

Three categories of inputs from you. Most are free; a couple are paid (and optional). Listed in priority order — top is needed before first run.

### 6.1 P0 — required before backend will start

| Input | Where to get | How to apply |
|---|---|---|
| **Docker Desktop running** | Already installed | Start the app |
| **NEXTAUTH_SECRET** in `.env` | Generated by `.\scripts\gen_nextauth_secret.ps1` | Already filled in |
| **PFIP_USER_PASSWORD_HASH** in `.env` | Generated by `python .\scripts\make_password_hash.py` | Already filled in (password = `pfip-local-2026`) |

### 6.2 P1 — recommended free API keys (each 2 min to register)

These unlock specific data streams. Without them, the corresponding adapter logs a warning and returns empty — nothing crashes. With them, you get data.

| Env var | Register at | Unlocks | Tier |
|---|---|---|---|
| `FRED_API_KEY` | https://fred.stlouisfed.org/docs/api/api_key.html | US macro backbone (CPI, rates, yields, VIX, DXY) | Free, 120 req/min |
| `FINNHUB_API_KEY` | https://finnhub.io | Earnings calendar + econ calendar + US news | Free, 60 req/min |
| `TIINGO_API_KEY` | https://tiingo.com | US EOD quality + news | Free, 1000/day |
| `ALPHA_VANTAGE_API_KEY` | https://www.alphavantage.co/support/#api-key | Backup US/FX/commodities | Free, 25/day (tight) |
| `POLYGON_API_KEY` | https://polygon.io | US delayed snapshots | Free, EOD only |
| `ALPACA_API_KEY` + `ALPACA_API_SECRET` | https://alpaca.markets | Paper trading data | Free |
| `EIA_API_KEY` | https://www.eia.gov/opendata/register.php | US energy data (oil, gas, refining) | Free, 5000/hr |
| `NASDAQ_DATA_LINK_API_KEY` | https://data.nasdaq.com/sign-up | Commodities + global bonds + UN Comtrade | Free, unlimited on free sets |
| `COINGECKO_API_KEY` | https://www.coingecko.com/api/pricing | Crypto prices/market cap (10k crypto assets) | Free, 10k calls/month |
| `EXCHANGERATE_API_KEY` | https://www.exchangerate-api.com | Forex 170+ pairs (backup to Frankfurter) | Free, 1500/month |
| `ETHERSCAN_API_KEY` | https://etherscan.io/apis | ETH/ERC-20 self-custody address tracking | Free, 5/sec |
| `BSCSCAN_API_KEY` | https://bscscan.com/apis | BSC chain (if you hold BNB chain assets) | Free, 5/sec |
| `SOLSCAN_API_KEY` | https://pro-api.solscan.io | SOL self-custody | Free tier |
| `NEWSAPI_API_KEY` | https://newsapi.org | General financial news aggregator | Free, 100/day, 24h delay |
| `MARKETAUX_API_KEY` | https://www.marketaux.com | Aggregator alternative | Free, 100/day |
| `CRYPTOPANIC_API_KEY` | https://cryptopanic.com/developers/api | Crypto news aggregator | Free, 500/day |
| `REDDIT_CLIENT_ID` + `REDDIT_CLIENT_SECRET` + `REDDIT_USER_AGENT` | https://www.reddit.com/prefs/apps (create "script" app) | Reddit live stream | Free, 100/min |
| `NEYNAR_API_KEY` | https://neynar.com | Farcaster crypto-social | Free tier |
| `GROQ_API_KEY` | https://console.groq.com | Cloud LLM fallback | Free tier |
| `SENTRY_DSN` | https://sentry.io | Error tracking | Free tier |
| `LANGSMITH_API_KEY` | https://smith.langchain.com | LLM call tracing | Free tier |

### 6.3 P2 — needs setup beyond just a key

| Input | What's involved |
|---|---|
| **Dedicated Telegram account** | New SIM/virtual number; register on Telegram; get api_id + api_hash from https://my.telegram.org; fill `TELEGRAM_API_ID` / `TELEGRAM_API_HASH`; on first run, login interactively to create session file. Recommended: don't use your personal account (ban risk). |
| **Telegram bot for outbound alerts** | Create via @BotFather on Telegram; fill `TELEGRAM_BOT_TOKEN` + `TELEGRAM_BOT_CHAT_ID` (your personal chat with the bot). |
| **Bluesky** | Create account at bsky.app; Settings → App passwords; fill `BLUESKY_HANDLE` + `BLUESKY_APP_PASSWORD`. (Public search works without — these only raise rate limits.) |

### 6.4 Personal data (CSV uploads)

You upload these manually via the Tax page (no API connections — for your safety). Tell me which of these you actually use so I focus the adapter testing on those:

- [ ] Zerodha
- [ ] ICICIdirect
- [ ] Groww
- [ ] INDmoney
- [ ] Vested
- [ ] WazirX
- [ ] CoinDCX
- [ ] Binance
- [ ] Coinbase
- [ ] Kraken

### 6.5 Knowledge base (optional, Stage 3+)

For the agent to cite trading books, you need to acquire them legally and place at `data/kb_sources/`. The 20-book recommended list is in the v0.5 plan Section 10. Folder is gitignored so book PDFs never enter version control.

---

## 7. Approval tracker

Mark each item with one of: **OK** (approve current), **SWAP** (use alternative — name it), **SKIP** (don't include), **MORE** (need more info before deciding).

You can paste back like:
```
5.1: OK
5.4: SKIP (no self-custody crypto)
5.18: SKIP (no dedicated TG yet)
5.25: MORE (research best LLM)
6.4: Zerodha + INDmoney + WazirX only
all others: OK
```

### Data sources

| # | Item | Status |
|---|---|---|
| 7.1 | Crypto OHLCV — Coinbase + Kraken + Bybit + OKX (no key) | _ |
| 7.2 | Crypto on-chain — DefiLlama + CoinMetrics + mempool.space + Glassnode free + Etherscan + Solscan | _ |
| 7.3 | Crypto derivatives — Coinglass free + Deribit | _ |
| 7.4 | Crypto self-custody addresses — mempool/Etherscan/Solscan **(skip if you don't hold non-exchange crypto)** | _ |
| 7.5 | US equities EOD — yfinance + Stooq + Tiingo (free key) | _ |
| 7.6 | US fundamentals — SEC EDGAR (no key) | _ |
| 7.7 | US earnings + econ calendar — Finnhub (free key) | _ |
| 7.8 | Indian equities EOD — jugaad-data + NSE/BSE bhavcopy | _ |
| 7.9 | Indian fundamentals — Screener.in scrape | _ |
| 7.10 | Indian mutual funds — AMFI NAV daily | _ |
| 7.11 | FX — Frankfurter + RBI + ExchangeRate-API (free key, optional) | _ |
| 7.12 | Macro — FRED (free key) + DBnomics + World Bank + MOSPI + RBI | _ |
| 7.13 | Commodities — yfinance futures + LBMA + EIA (free key) | _ |
| 7.14 | **NASDAQ Data Link — commodities, global bonds, UN Comtrade (free key) — NEW** | _ |
| 7.15 | News RSS feeds (10+ sources) | _ |
| 7.16 | GDELT global news firehose | _ |
| 7.17 | CryptoPanic news (free key) | _ |
| 7.18 | NewsAPI / Marketaux (free keys, aggregators) | _ |
| 7.19 | Reddit (PRAW) — 6 subreddits | _ |
| 7.20 | Telegram (Telethon) — 15 channels — **needs dedicated account** | _ |
| 7.21 | Bluesky firehose | _ |
| 7.22 | Farcaster (Neynar, free key) | _ |
| 7.23 | arXiv q-fin daily | _ |
| 7.24 | SEC 8-K RSS | _ |
| 7.25 | Polymarket + Kalshi prediction markets | _ |

### Models

| # | Item | Status |
|---|---|---|
| 7.26 | LLM (chat agent) — **DEFER until Task #1 benchmark research is done** | _ |
| 7.27 | Embeddings — nomic-embed-text (current) or BGE-M3 (upgrade)? | _ |
| 7.28 | Sentiment (news) — ProsusAI/finbert | _ |
| 7.29 | Sentiment (crypto-social) — ElKulako/cryptobert | _ |
| 7.30 | Signal model — LightGBM as primary | _ |
| 7.31 | Regime detector — HMM 3-state | _ |
| 7.32 | Foundation time-series models (TTM/Chronos/Moirai) — opt-in only | _ |

### Evaluation framework

| # | Item | Status |
|---|---|---|
| 7.33 | RAGAS for retrieval quality | _ |
| 7.34 | **FinQA for numerical reasoning — NEW** | _ |
| 7.35 | **FinanceBench for end-to-end RAG over filings — NEW** | _ |
| 7.36 | Custom 50-100 Q/A finance eval over your specific watchlist | _ |

### Infrastructure

| # | Item | Status |
|---|---|---|
| 7.37 | TimescaleDB | _ |
| 7.38 | Qdrant | _ |
| 7.39 | Redis | _ |
| 7.40 | Prefect | _ |
| 7.41 | MLflow | _ |
| 7.42 | Ollama (local LLM) | _ |
| 7.43 | Sentry + Uptime Kuma | _ |
| 7.44 | Next.js + FastAPI app stack | _ |

### CSV adapters (which brokers do you actually use)

| # | Broker | Status |
|---|---|---|
| 7.45 | Zerodha | _ |
| 7.46 | ICICIdirect | _ |
| 7.47 | Groww | _ |
| 7.48 | INDmoney | _ |
| 7.49 | Vested | _ |
| 7.50 | WazirX | _ |
| 7.51 | CoinDCX | _ |
| 7.52 | Binance | _ |
| 7.53 | Coinbase | _ |
| 7.54 | Kraken | _ |

---

## 8. How to work through this

Tell me your decisions in any format. Easiest:

```
7.4: SKIP (no self-custody)
7.18: SKIP (don't need news aggregator)
7.20: SKIP (no dedicated Telegram yet)
7.26: defer per Task #1
7.45-7.54: only Zerodha, INDmoney, WazirX
all others: OK
```

I won't run anything new until you confirm. The existing build is already running per `FIRST_RUN.ps1`; this approval pass shapes what we add/remove from here.
