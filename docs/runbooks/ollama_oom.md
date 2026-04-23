# Runbook — Ollama OOM under load

## Symptoms

- Agent chat responses time out or return "model unavailable".
- `pfip-ollama` container restarts in a loop (`docker ps` shows short uptime).
- Host RAM pressure: Docker Desktop dashboard shows >90% memory.
- Backend logs: `httpx.ConnectError: [Errno 111] Connection refused` on 11434.
- Windows event log: "Docker Desktop backend was killed due to OOM".

## Diagnosis

1. Check container state:
   ```powershell
   docker inspect pfip-ollama --format "{{.State.Status}} exit={{.State.ExitCode}} oom={{.State.OOMKilled}}"
   ```
   `oom=true` confirms the kernel killed it.
2. See which models are loaded:
   ```powershell
   docker exec -it pfip-ollama ollama ps
   ```
3. Check concurrent request count — simultaneous chat + embedding requests can double
   peak memory.

## Fix

### Primary

- Restart the container:
  ```powershell
  docker compose -f infra/docker-compose.yml restart ollama
  ```
- Raise Docker Desktop memory cap (Settings → Resources → Memory) to at least **12 GB**
  for mistral-7b, **8 GB** for nomic-embed-text-only workloads.
- Serialise agent + KB embedding: set `OLLAMA_NUM_PARALLEL=1` in the container env.

### Fallback

- Switch default model to a smaller quant:
  ```powershell
  docker exec -it pfip-ollama ollama pull mistral:7b-instruct-q4_0
  # then set LLM_DEFAULT_MODEL=mistral:7b-instruct-q4_0 in .env
  ```
- Enable cloud fallback: set `GROQ_API_KEY` and `LLM_CLOUD_FALLBACK=groq/llama-3.1-8b-instant`;
  the agent router will use Groq when local is slow.

### Nuclear

- Stop `ollama` entirely; run agent in cloud-only mode
  (`LLM_ROUTE_STRATEGY=cloud_only`).
- Move Ollama to a dedicated GPU box later; network-attach via the pfip-net tailnet.

## Prevention

- Set Docker Desktop memory to `host_ram / 2` at minimum.
- Keep `OLLAMA_NUM_PARALLEL=1` unless the host has >32 GB RAM.
- Nightly job unloads idle models: `ollama stop <model>` at 03:00 IST.
- Uptime Kuma HTTP(S) check on `http://localhost:11434/api/tags` every 60s.

## Last occurred

None yet (Stage 0 fresh install).
