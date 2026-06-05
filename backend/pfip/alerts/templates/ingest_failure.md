Ingest failure — {source}

A scheduled ingest flow failed:

- **Source**: {source}
- **Consecutive failures**: {consecutive_failures}
- **Last error**: {last_error}
- **Last successful run**: {last_success_at}

Check `/api/v1/health/sources` for full state. Runbooks at `docs/runbooks/`. If this is the 3rd+ consecutive failure, the source will auto-disable; manual intervention required.
