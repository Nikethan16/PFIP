"""Standalone operational scripts for PFIP.

These are plain-async entrypoints (no Prefect, no Docker) intended to run
against ``DATABASE_URL`` from any host — local Docker, a bare venv, or a
GitHub Actions runner pointed at managed Postgres (Neon). They reuse the same
underlying ingest/feature/regime/signal functions the Prefect flows call.

Making ``scripts`` a package lets them run as ``python -m scripts.<name>``
from the backend directory.
"""
