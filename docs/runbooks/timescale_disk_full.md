# Runbook — TimescaleDB disk full / hot partition breached

## Symptoms

- Backend writes to `ohlcv` or `portfolio_tx` raise
  `psycopg.errors.DiskFull: could not extend file`.
- Uptime Kuma alert: disk >90% on the Docker volume `timescale_data`.
- Prefect ingest flows fail in a cascade — ingest, feature-build, shadow portfolio.
- `docker logs pfip-timescaledb` shows
  `PANIC: could not write to file ... No space left on device`.

## Diagnosis

1. Check disk usage on the host:
   ```powershell
   docker system df -v
   ```
2. Check hypertable chunk sizes:
   ```sql
   SELECT hypertable_name, pg_size_pretty(sum(total_bytes)) AS total
   FROM timescaledb_information.chunks
   GROUP BY 1 ORDER BY sum(total_bytes) DESC;
   ```
3. Identify the hot partition:
   ```sql
   SELECT show_chunks('ohlcv', older_than => INTERVAL '7 days');
   ```

## Fix

### Primary

- Enable (or trigger) Timescale compression on older chunks:
  ```sql
  ALTER TABLE ohlcv SET (timescaledb.compress, timescaledb.compress_segmentby = 'symbol');
  SELECT compress_chunk(c) FROM show_chunks('ohlcv', older_than => INTERVAL '30 days') c;
  ```
  Typical 10–20x reduction on OHLCV.
- Drop redundant per-minute data for symbols where you only need daily:
  ```sql
  DELETE FROM ohlcv WHERE timeframe = '1m' AND symbol = 'BTC-USD' AND time < NOW() - INTERVAL '90 days';
  VACUUM FULL ohlcv;
  ```

### Fallback

- Extend the Docker volume: in Docker Desktop → Settings → Resources → Disk image size,
  raise by 20 GB, Apply, restart Docker. (Existing volume data preserved.)
- Migrate `timescale_data` to a roomier drive by exporting + re-importing via the backup
  procedure in `docs/BACKUP.md` section 5.

### Nuclear

- Drop and re-ingest: if history is available from source, `TRUNCATE ohlcv` on the oldest
  partitions, then re-run ingest flows. **Back up first** — this is irreversible.

## Prevention

- Retention policy on `ohlcv`:
  ```sql
  SELECT add_retention_policy('ohlcv', INTERVAL '3 years');
  ```
- Compression policy:
  ```sql
  SELECT add_compression_policy('ohlcv', INTERVAL '30 days');
  ```
- Uptime Kuma rule: alert when TimescaleDB volume >80%.
- Dashboard card on frontend Ops page: size of each hypertable, refreshed nightly.

## Last occurred

None yet (Stage 0 fresh install).
