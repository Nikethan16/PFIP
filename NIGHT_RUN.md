# PFIP Overnight Mission — Agent Brief (Full Autonomy)

**For:** an agent running unattended (Antigravity / Claude Code / equivalent).
**Duration:** up to 6 hours wall-clock. Stop by 06:00 IST regardless.

## STOP — Read this first

- **You have been granted FULL PRE-APPROVAL for every action within the safety rails in Section 4.**
- **Do NOT ask the user to confirm commands. They are not at the keyboard.**
- **Do NOT pause for approval on file edits, shell commands, package installs, or config changes within scope.**
- **Act. Decide. Move. Log your reasoning. The user reads the log in the morning, not in real time.**

The only time you stop and wait is: (a) all work is complete; (b) you hit a safety rail; (c) the wall-clock budget is up.

## Research authority

You have web access AND full authority to:

- **Evaluate and swap** any library, model, or API in this project if you find a demonstrably better open-source alternative. Document the comparison and rationale in `OVERNIGHT_LOG.md` — a 2-sentence justification is enough.
- **Research and select** the best local LLM for the agent's reasoning layer. Current default is Mistral-7B-Instruct via Ollama. If you find a better open-source model for finance reasoning that runs on ~16 GB RAM (e.g., Llama-3.1-8B, Qwen-2.5, DeepSeek-R1-distill, finance-finetuned variants), benchmark / read papers, pick one, pull it, wire it in.
- **Research and select** the best sentiment models. Current defaults are ProsusAI/finbert and ElKulako/cryptobert. If a better open-source finance-sentiment model exists (check HuggingFace leaderboards, recent arXiv papers, finance-NLP benchmarks), swap it.
- **Research and select** the best forecasting models / foundation models for time-series (Chronos vs TimesFM vs Moirai vs TTM vs newer). Pick what actually works best on financial data per recent benchmarks.
- **Research and select** the best embedding model for RAG (current: nomic-embed-text). If bge-m3, gte-large, or a newer open-source embedder benchmarks higher on retrieval quality, switch.
- **Find and use additional free data sources** you discover in research that weren't in the original plan, as long as they're free-tier, ToS-compliant for personal use, and open or have permissive APIs.
- **Write new code** to integrate better tools you found. You don't need to stick to the exact modules in `pfip/`.

**Selection criteria (apply in this order):**
1. Open-source (Apache 2.0, MIT, BSD preferred; avoid GPL if possible)
2. Actively maintained (commits in last 6 months)
3. Benchmarked on finance / time-series data (not just general NLP)
4. Runs within hardware envelope (16 GB RAM, CPU acceptable, GPU optional)
5. Has real docs and community

**Autonomy level:** full. You pick what to work on, research when stuck, evaluate alternatives, implement, validate, commit, move on. The starting task list in Section 8 is a floor, not a ceiling — exceed it if you have time.
**Trust contract:** user has approved all actions within the safety rails in Section 4. No need to ask for permission during the run.

---

## 1. Mission

Take PFIP at `C:\Users\gaura\OneDrive\Desktop\PFIP_app\` from "scaffolded" to "actually works end-to-end" by morning. This means:

- Docker stack runs clean.
- Database migrated and populated with real market data across all three markets (crypto majors, US watchlist, Indian watchlist).
- News pipeline has ingested at least one full cycle.
- ML engines (regime, features, calibration) have run successfully at least once.
- Dashboard renders real data at http://localhost:3000.
- Tests that were passing still pass; tests that were failing either fixed or clearly documented as known issues.
- A `MORNING_REPORT.md` summarises state, decisions made, and anything needing user input.

You own the how. The list in section 8 below is a starting point, not a script.

---

## 2. Operating loop

For every non-trivial issue, run this loop:

```
  observe  →  research  →  plan  →  implement  →  validate  →  commit  →  log
     ↑                                                                    ↓
     └────────── if broken again, restart at observe ────────────────────┘
```

- **Observe.** Read the actual error. Read the logs. Read the relevant code. Don't guess.
- **Research.** If the error isn't obvious: search the web, read the library's docs, check the library's GitHub issues, look at similar patterns elsewhere in the codebase. Spend up to 10 minutes researching before implementing. For known-hard libs on Windows (shap, vectorbt, lightgbm, transformers, pandas-ta), research first — wheels + build requirements + common Windows pitfalls.
- **Plan.** Before touching code, write (to log) what you're about to do and why. Two-line plan.
- **Implement.** Make the change. Keep diffs surgical.
- **Validate.** Re-run the thing that was broken. Confirm it now works. If it worked before, run its tests too to confirm you didn't regress.
- **Commit.** `git add -A && git commit -m "<short message>"` after every material change that improves the state. This gives easy rollback. Never `git push`.
- **Log.** Append to `OVERNIGHT_LOG.md` with timestamp, what changed, outcome.

If the same issue fails three fixes in a row, skip the whole area, log "blocked: needs human," and move to the next priority. Don't waste the night on one thing.

---

## 3. Autonomy contract — you CAN (no approval needed for any of these)

- Run any terminal / PowerShell / docker / python / npm / pnpm command within the project.
- Read, write, edit, delete any file inside `C:\Users\gaura\OneDrive\Desktop\PFIP_app\` (except the hard-blocked list in section 4).
- Create new files, directories, modules, scripts, runbooks, tests, docs.
- Modify `backend/requirements.txt` or `frontend/package.json` — swap, add, remove deps as needed.
- Install additional Python/Node packages that solve real problems. Prefer OSS + active maintenance + good benchmarks.
- Rewrite Alembic migrations if they conflict or fail. Merge branches. Collapse if needed.
- Refactor existing code to integrate better tools found via research.
- **Research and swap models** (LLMs, sentiment classifiers, forecasters, embedders) for better OSS alternatives. Pull via Ollama or HuggingFace, wire in, test.
- **Add new data sources** you discover in research if they're free-tier + ToS-compliant for personal use.
- **Add new endpoints, new tables, new Prefect flows** that weren't in the original scaffold if you identify gaps that make the system demonstrably better.
- Pull Docker images, build images, run containers.
- Web-search freely. Compare options. Read papers. Check benchmarks. Read GitHub issues. Use all of it.
- Modify ML code to add guards, fallbacks, or replace broken impl with working impl.
- Write new tests when you add new code. Fix flaky existing tests.
- `git commit` locally as often as useful — after every material improvement.

---

## 4. Hard safety rails — you CANNOT

- **No `git push`** to any remote. Ever.
- **No destructive commands**: `rm -rf`, `docker volume rm`, `docker system prune -a --volumes`, `DROP DATABASE`, `ALTER TABLE ... DROP`, `git reset --hard`, `git checkout -- .` without first committing.
- **No spending** of user's money: skip any adapter that requires a paid key (Glassnode paid tier, paid Polygon, paid Alpaca SIP).
- **No `.env` edits** that change or remove existing values. You may read `.env` but not write to it. If a missing key is needed, log it in `MORNING_REPORT.md` instead.
- **No modifications to `docs/CONTRACTS.md`** — that's the authoritative API + schema spec. If behaviour needs to change, change the implementation to match the contract, not the reverse.
- **No disabling of failing tests** to make CI green. Fix them properly or `@pytest.mark.skip(reason="blocked: <specific>")` with a clear reason logged.
- **No new Docker services** added to `infra/docker-compose.yml`. You may edit existing services' config (env, command, healthcheck) if justified.
- **No opening of new host ports** beyond what's in docker-compose.
- **No system-level changes**: no registry edits, no Windows services, no firewall rules, no `setx` global env, no Windows Scheduled Tasks creation without logging.
- **No access to files outside** the project root. Plan + tracker at `C:\Users\gaura\OneDrive\Desktop\PFIP_v0.5\` is read-only reference only.
- **No replacing major architecture**: don't swap TimescaleDB for sqlite, don't swap Next.js for Streamlit, don't replace FastAPI/Pydantic contract layer. (Swapping LLMs, sentiment models, forecasters, embedders — all fine, that's Section 2 research authority.)
- **No live trading adapters** activated. `brokers/` module stays execution-less in v1.
- **No uploading** of user's local data (CSVs, env values, DB snapshots) to any external service during research.

When in doubt: act per autonomy contract, log decision with reasoning. Only skip with "deferred: needs user decision" if the action itself might cause harm and you can't determine otherwise.

---

## 5. Priority heuristic

When deciding what to work on next, score each candidate by:

1. **Unblocks downstream work** (highest weight). E.g., Docker not up blocks everything → always #1.
2. **Converts scaffolded code into real data** (high). Running an ingest flow is more valuable than running a test.
3. **Compounds** (medium). Fixing a shared lib issue helps many modules.
4. **Has a clear validation step** (medium). Prefer tasks where you can prove it works.
5. **Low risk of regressing working things** (medium).
6. **Nice-to-have polish** (low). Docs, typos, formatting — only touch if everything else is done.

Don't sequentialise — if a task is blocked or you're waiting (e.g., `ollama pull` running), work on another track in parallel.

---

## 6. Research mandate

You have web access. Use it. This project involves Python libs that sometimes have Windows gotchas, edge cases in free-tier APIs, and rapidly-changing library APIs. Specifically — search the web when:

- A library raises an unexpected error. Check the library's GitHub issues first, then Stack Overflow.
- A package fails to install. Is there a known wheel issue? An alternative? A `--no-binary` flag?
- An API returns an unexpected shape. Has it changed? Is there a migration note in the provider's changelog?
- You're about to swap one library for another. Is the alternative actively maintained? Does it have better Python 3.12 support?

Cite the URL of any page that informed a decision, in `OVERNIGHT_LOG.md`. This keeps the user able to audit reasoning in the morning.

Don't research gratuitously. If the fix is obvious from the error message, just fix it.

---

## 7. Validation discipline

Every change must be validated before you move on. Validation takes different forms:

- **Code change to a service** → restart the container, re-run the failing command, confirm it now works.
- **Config change** → confirm the service picks it up and doesn't crash-loop.
- **New ingest flow run** → confirm the target table has at least some rows (`docker exec pfip-timescaledb psql -U pfip -c "SELECT count(*) FROM <table>"`) and no obvious garbage data.
- **Library swap** → run any affected tests + verify the module that depended on it still imports.
- **Schema change** → run `alembic upgrade head` then `alembic check` (if available) or at minimum verify the table exists.

Never log "done" for something you haven't actually verified. It's fine to log "skipped — validation failed, blocked" if you can't verify.

---

## 8. Suggested starting order (not a script)

Rough priority; reorder if you see a better path:

### Tier 1 — Stack up and stable
- Run `.\FIRST_RUN.ps1` as-is. Fix whatever breaks. Get to green `docker compose ps` and green `.\scripts\health.ps1`.
- Run migrations to `head` (revision 0005).
- Sanity-check: http://localhost:8000/api/v1/health returns 200.

### Tier 2 — LLM models + first ingest
- `docker exec pfip-ollama ollama pull mistral:7b-instruct` and `ollama pull nomic-embed-text`. Do this EARLY so it runs in the background while you do other work.
- First BTC daily ingest end-to-end. Verify row count > 1000.
- ETH, SOL, BNB ingest.

### Tier 3 — Broader market data
- US watchlist (~10 tickers): SPY, QQQ, VTI, AAPL, MSFT, NVDA, GOOGL, META, AMZN, TSLA.
- Indian watchlist (~20 largecaps from NIFTY50).
- AMFI mutual fund NAVs.
- FX (Frankfurter + RBI).
- Macro (DBnomics; FRED needs a key, skip if not set).
- News pipeline one full cycle (GDELT + Google News RSS + Moneycontrol + Yahoo ticker RSS + SEC 8-K — others need keys, skip those).

### Tier 4 — Compute
- Compute features across all ingested OHLCV.
- Run HMM regime detection per market.
- Run one LightGBM baseline signal backtest to verify the engine works end-to-end.
- Run calibration once (output will be thin — that's fine).
- Run shadow portfolio reconcile once.

### Tier 5 — UI verification
- Hit http://localhost:3000 — should render.
- Verify BTC candle chart has data on dashboard.
- Verify watchlist page shows ingested tickers with prices.
- Verify signals page either shows signals or a clean empty state.
- Verify chat page loads (may not respond if Ollama still downloading).

### Tier 6 — Tests
- Run `docker exec pfip-backend pytest -q`. Record pass/fail counts.
- For any failures: triage. Fixable in < 10 min? Fix. Otherwise log and move on.

### Tier 7 — Nice-to-haves
- Deploy Prefect schedules.
- Start a Prefect worker.
- Backfill historical data further (5 years back) on the most important symbols.
- Populate the knowledge base if any PDFs exist in `data/kb_sources/` (likely empty — skip if so).

---

## 9. Git discipline

Initialize git if it isn't already:

```bash
git init
git add -A
git commit -m "pre-overnight snapshot"
```

Then commit after every material improvement. Suggested commit message format:

```
<tier>: <short what>
- why
- validation
```

Examples:
```
tier1-stack: fix atproto version conflict in requirements
- atproto==0.0.48 pinned incompatible httpx; upgraded to >=0.0.55
- validated: uv pip install -r requirements.txt succeeds
```

```
tier2-ingest: first BTC daily ingest
- pulled 5y of BTC-USD daily from Coinbase via ccxt
- validated: 1827 rows in ohlcv table, prices sane (spot-checked 2020 crash + 2024 halving)
```

If you break something, `git log` shows the sequence and you can `git revert` a specific commit rather than rolling everything back.

---

## 10. Morning report

When you stop (either done or time-limited), write `MORNING_REPORT.md` at the project root with this structure:

```markdown
# Overnight run — <date>

## Summary
<3 sentences: what's working, what isn't, what user should look at first>

## Tier status
- Tier 1: ✅ / ⚠️ / ❌ <one line>
- Tier 2: ...
- ... through Tier 7

## Data state
- OHLCV rows per market
- News items ingested
- Features computed: yes/no for each market
- Calibration reports: N
- Shadow portfolio positions: N

## Decisions I made
<bulleted list of notable autonomous choices: lib swaps, skipped modules, config tweaks>

## Blocked items (need you)
<what requires human decision — be specific>

## Quick-start for tomorrow
<3–5 bullets: specific URLs to open, specific commands to run>

## Git state
- Commits added tonight: N
- Latest commit: <hash> <message>
- Anything uncommitted: <list>
```

Keep it scannable. 2-minute read max.

---

## 11. Escalation / graceful exit

You exit gracefully when any of these hit:

- Wall-clock budget (6 hours) reached.
- Tier 1 fails three retries — something fundamental is wrong, don't flail.
- Repeated safety-rail conflicts — stop before you do damage.
- Error rate climbing (e.g., every command fails) — network down, Docker down, disk full. Don't keep hammering.

Graceful exit means: commit current state, write `MORNING_REPORT.md`, stop.

---

## 12. Final trust note

The user is traveling and cannot respond. They've chosen to trust your judgment on a bounded problem. Treat the trust seriously:

- Prefer reversible over clever.
- Prefer validated over fast.
- Prefer logged over hidden.
- When unsure, do less.

Have a good night.
