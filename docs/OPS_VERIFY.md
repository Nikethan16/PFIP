# Live verification checklist

Quick commands to confirm the data/news/research layers are actually working on
the VM (not just returning HTTP 200). Run after a deploy or a nightly pipeline.

Set once (from your machine, against the public Funnel URL):

```bash
BASE=https://apps.tail1d9a60.ts.net:8443
TOKEN=$(curl -s $BASE/api/v1/auth/login -H 'content-type: application/json' \
  -d '{"email":"<you>","password":"<pw>"}' | python -c 'import sys,json;print(json.load(sys.stdin)["token"])')
AUTH="Authorization: Bearer $TOKEN"
```

## 1. Keyed news sources are pulling (AV + NewsData)

The env-var name matters: the code accepts **either** `ALPHAVANTAGE_API_KEY` or
`ALPHA_VANTAGE_API_KEY` (and `NEWSDATA_API_KEY` / `NEWS_DATA_API_KEY`). After a
nightly run, both should appear in source-health with `consecutive_failures: 0`:

```bash
curl -s $BASE/api/v1/health/sources -H "$AUTH" \
  | python -c 'import sys,json;[print(s["source"],s["last_rows"],"fails="+str(s["consecutive_failures"]),s["last_error"]) for s in json.load(sys.stdin)["sources"] if s["source"] in ("alphavantage","newsdata")]'
```

- **Rows > 0, fails = 0** → working.
- **Row absent** → key not set in the VM `.env` (`~/pfip/backend/.env`).
- **fails > 0 with a key error** → wrong key value (the *name* is now tolerant).

To force a run instead of waiting for 02:30 UTC:
`ssh` to the VM → `sudo systemctl start pfip-pipeline.service` → re-check.

## 2. Deep Research returns live fundamentals (untracked names)

```bash
curl -s $BASE/api/v1/research -H "$AUTH" -H 'content-type: application/json' \
  -d '{"query":"Waree Energies"}' \
  | python -c 'import sys,json;d=json.load(sys.stdin);print("src",(d.get("fundamentals") or {}).get("source"),"metrics",len((d.get("fundamentals") or {}).get("key_metrics") or {}));print(d["dossier_markdown"][:400])'
```

Expect `src=screener` (India) or `src=alphavantage` (US) with **metrics > 0** and
a real dossier. India → screener.in; US → Alpha Vantage; both reachable from the VM.

## 3. Chat can research any company

```bash
curl -s $BASE/api/v1/agent/chat -H "$AUTH" -H 'content-type: application/json' \
  -d '{"message":"research Waree Energies — fundamentals and the bull/bear case"}' --max-time 60 | tail -c 1200
```

Expect a grounded answer citing `db://research/WAAREEENER...` (live fundamentals),
not an "LLM unavailable" stub.

## 4. Qdrant / RAG

```bash
curl -s $BASE/api/v1/health/deep -H "$AUTH" | python -c 'import sys,json;print(json.load(sys.stdin)["checks"]["qdrant"])'
```

- `{'ok': True, 'code': 200}` → healthy.
- `ok: False` with a code/error → fix `QDRANT_URL` / `QDRANT_API_KEY` in the VM
  `.env`. Chat still works without it (KB retrieval degrades to empty), just
  ungrounded on the book knowledge base.

## 5. Telegram community channels (optional)

No-ops unless `TELEGRAM_API_ID` + `TELEGRAM_API_HASH` are set. Point it at the
channels you trust with `TELEGRAM_CHANNELS` (comma-separated usernames) in the
VM `.env` — no code change needed. Then check `telegram` in `/health/sources`.
