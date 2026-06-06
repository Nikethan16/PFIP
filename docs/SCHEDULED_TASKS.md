# Scheduled Tasks — Prefect Deployments & Cron Mapping

Full table from plan **Section 12.2**, with the concrete Prefect deployment name and cron
expression each row maps to. All times are **Asia/Kolkata (IST, UTC+05:30)** unless marked.
Deployment specs live in `/schedules/`.

At Stage 0, only the infra-hygiene rows are wired. Ingest / signal / tax rows come online
stage-by-stage.

> **Catalogue fixed (2026-06-04 feature build).** The Prefect deployment catalogue
> (`schedules/prefect_deployments.py`) had **8 of its 21 `flow_path`s broken** (wrong
> module/callable names + a finnhub import bug), so those scheduled tasks silently never
> registered — they looked configured here but never ran. All **21 now resolve**, the missing
> `morning-brief` Prefect flow wrapper was built, and a new test
> (`test_deployments_resolve.py`) imports every deployment's flow to keep the catalogue from
> regressing. The signal rows remain **stage-gated and OFF** (`FEATURE_ML_SIGNALS=false`,
> stage 3) — "resolves" means the deployment registers, not that ML signals are producing
> data. See `docs/CHANGELOG.md` "Feature build pass".

---

## 1. Data ingest

| Purpose                       | Cadence              | Cron (IST)      | Prefect deployment                 | Stage  |
| ----------------------------- | -------------------- | --------------- | ---------------------------------- | ------ |
| Crypto OHLCV (BTC/ETH/SOL)    | every 5 min          | `*/5 * * * *`   | `ingest-crypto-ohlcv/live`         | 1      |
| Crypto daily close            | 05:35 IST            | `35 5 * * *`    | `ingest-crypto-daily/eod`          | 1      |
| Indian equities daily         | weekdays 16:30 IST   | `30 16 * * 1-5` | `ingest-equity-nse-daily/eod`      | 2      |
| Indian derivatives (F&O)      | weekdays 16:45 IST   | `45 16 * * 1-5` | `ingest-equity-nse-fo-daily/eod`   | 2      |
| US equities daily             | weekdays 02:30 IST   | `30 2 * * 2-6`  | `ingest-equity-us-daily/eod`       | 2      |
| Fundamentals refresh          | Sunday 04:00 IST     | `0 4 * * 0`     | `ingest-fundamentals/weekly`       | 2      |
| On-chain metrics (Glassnode)  | hourly               | `0 * * * *`     | `ingest-onchain-hourly/live`       | 1      |
| Macro (FRED / RBI)            | daily 06:00 IST      | `0 6 * * *`     | `ingest-macro-daily/eod`           | 1      |
| News RSS / NewsAPI            | every 15 min         | `*/15 * * * *`  | `ingest-news/live`                 | 3      |
| Reddit + Bluesky + Farcaster  | every 20 min         | `*/20 * * * *`  | `ingest-social/live`               | 3      |
| Telegram channels             | every 30 min         | `*/30 * * * *`  | `ingest-telegram/live`             | 3      |
| GDELT global events           | hourly               | `10 * * * *`    | `ingest-gdelt-hourly/live`         | 3      |
| FX rates (RBI + SBI TT)       | daily 18:00 IST      | `0 18 * * *`    | `ingest-fx-daily/eod`              | 1      |
| AMFI NAVs (Indian MF)         | weekdays 22:00 IST   | `0 22 * * 1-5`  | `ingest-amfi-nav-daily/eod`        | 2      |

## 2. Feature + signal

| Purpose                              | Cadence          | Cron (IST)      | Prefect deployment                | Stage |
| ------------------------------------ | ---------------- | --------------- | --------------------------------- | ----- |
| Feature recompute (PIT)              | after each ingest| chained         | `features-chained/*`              | 1     |
| Regime classifier update             | daily 06:30 IST  | `30 6 * * *`    | `regime-daily/eod`                | 2     |
| Signal generation per asset          | daily 07:00 IST  | `0 7 * * *`     | `signals-generate/eod`            | 4     |
| Calibration report (Brier/ECE)       | 1st Sat 08:00 IST| `0 8 1-7 * 6`   | `calibration-monthly/report`      | 4     |
| Backtest refresh on tracked models   | weekly Sun 03:00 | `0 3 * * 0`     | `backtest-refresh/weekly`         | 4     |

## 3. Portfolio + agent

| Purpose                               | Cadence               | Cron (IST)       | Prefect deployment            | Stage |
| ------------------------------------- | --------------------- | ---------------- | ----------------------------- | ----- |
| Shadow portfolio mark-to-market       | every 5 min, mkt-hours| `*/5 9-16 * * *` | `shadow-mtm/live`             | 1     |
| Real portfolio reconciliation         | daily 23:00 IST       | `0 23 * * *`     | `portfolio-reconcile/eod`     | 5     |
| Morning brief generation              | daily 07:30 IST       | `30 7 * * *`     | `agent-morning-brief/daily`   | 3     |
| Evening recap                         | daily 21:00 IST       | `0 21 * * *`     | `agent-evening-recap/daily`   | 3     |
| KB incremental ingest (if new docs)   | nightly 02:30 IST     | `30 2 * * *`     | `kb-incremental/nightly`      | 3     |

## 4. Tax + compliance

| Purpose                                  | Cadence              | Cron (IST)       | Prefect deployment            | Stage |
| ---------------------------------------- | -------------------- | ---------------- | ----------------------------- | ----- |
| Tax ledger refresh (STCG/LTCG/VDA)       | daily 23:30 IST      | `30 23 * * *`    | `tax-ledger-refresh/eod`      | 5     |
| Advance-tax reminder (Jun/Sep/Dec/Mar)   | 10th of month        | `0 8 10 3,6,9,12 *` | `advance-tax-reminder/monthly` | 5  |
| Schedule FA snapshot                     | 31 Dec 23:55 IST     | `55 23 31 12 *`  | `schedule-fa-snapshot/yearly` | 5     |
| CA handoff packet                        | 15 May 06:00 IST     | `0 6 15 5 *`     | `ca-handoff/yearly`           | 5     |

## 5. Infra / ops hygiene (active from Stage 0)

| Purpose                                  | Cadence              | Cron (IST)       | Prefect deployment                    | Stage |
| ---------------------------------------- | -------------------- | ---------------- | ------------------------------------- | ----- |
| Full backup (Timescale + Qdrant + MLflow)| nightly 01:00 IST    | `0 1 * * *`      | `ops-backup/nightly`                  | 0     |
| Backup checksum verify                   | nightly 01:30 IST    | `30 1 * * *`     | `ops-backup-verify/nightly`           | 0     |
| Monthly archive                          | 1st of month 01:45   | `45 1 1 * *`     | `ops-backup-monthly/monthly`          | 0     |
| Quarterly restore drill reminder         | 1st Sat/quarter 09:00| `0 9 1-7 1,4,7,10 6` | `ops-restore-drill/reminder`      | 0     |
| Log rotation + purge                     | nightly 02:00 IST    | `0 2 * * *`      | `ops-log-rotate/nightly`              | 0     |
| Docker image update check                | Sunday 03:30 IST     | `30 3 * * 0`     | `ops-docker-image-check/weekly`       | 0     |
| Dependency update sweep (`uv lock -U`)   | 1st Sat/quarter      | manual trigger   | `ops-deps-refresh/quarterly`          | 0     |
| Secret rotation reminder                 | 1st Sat/quarter      | manual trigger   | `ops-secrets-rotate/quarterly`        | 0     |
| TimescaleDB compression policy           | nightly 03:00 IST    | `0 3 * * *`      | (DB policy, not Prefect)              | 0     |
| Ollama idle unload                       | nightly 03:00 IST    | `0 3 * * *`      | `ops-ollama-idle-unload/nightly`      | 0     |
| Uptime Kuma self-check                   | every 1 min          | native           | (Uptime Kuma internal)                | 0     |

---

## 6. Notes

- **Windows host:** Docker Desktop's clock drifts after sleep. Install
  `w32tm /resync` as a scheduled task to keep cron sane.
- **Market closures:** NSE / BSE holiday list is read from `/backend/pfip/universe/nse_holidays.yml`;
  weekday cron rows skip those dates automatically via a conditional task.
- **Time zones:** Prefect runs UTC by default; all crons above are translated to UTC in
  the deployment spec. Keep IST labels in this doc for sanity.
- **Retries:** every data-ingest deployment retries 3× with base delay 60s. Signal /
  model deployments retry 2×.
- **Alerts:** any deployment failing twice in a row pages via Uptime Kuma + Telegram (if
  wired).
- When adding a new scheduled task: (1) write the flow, (2) register in `/schedules/`,
  (3) add a row here, (4) add an Uptime Kuma monitor.
- **FX rates** (the `ingest-fx-daily` row): the flow now actually populates the `fx_rates`
  table from Frankfurter (`pfip.ingest.macro.fx_rates`) — this is what unlocks USD→INR
  mark-to-market and tax conversions. Manual backfill if you need history immediately:
  `python -c "import asyncio; from pfip.ingest.macro.fx_rates import ingest_fx_rates; asyncio.run(ingest_fx_rates(mode='backfill', lookback_days=730))"`.
- **Signal generation** (the `signals-generate/eod` row): stays a no-op until
  `FEATURE_ML_SIGNALS=true` AND the asset has enough OHLCV history. The flow logs and exits
  when the flag is off — registering the deployment does **not** turn signals on.
- **Full backup** (the infra-hygiene row): now backed by the real `scripts/backup.py` via the
  `backup-daily` Prefect flow (see `docs/BACKUP.md` §0).
