"""Local dev launcher for the PFIP backend on Windows.

Sets the selector event-loop policy (async psycopg breaks on the default
Proactor loop) and loads ``.env`` from the repo root. Run from the repo root:

    ../.venv/Scripts/python.exe backend/run_local.py
"""

from __future__ import annotations

import asyncio
import os
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Ensure the package is importable and .env (repo root) resolves regardless of CWD.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
os.chdir(_ROOT)

import uvicorn  # noqa: E402

if __name__ == "__main__":
    uvicorn.run(
        "pfip.api.main:app",
        host="127.0.0.1",
        port=8000,
        loop="asyncio",
        log_level="info",
    )
