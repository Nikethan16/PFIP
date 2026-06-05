# PFIP backend — Python 3.12 slim image using uv for dependency management
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_SYSTEM_PYTHON=1 \
    UV_LINK_MODE=copy \
    UV_HTTP_TIMEOUT=600

# System deps: build tools for some C extensions (psycopg, numpy etc.) plus libpq runtime.
# Hardened against flaky Debian mirrors: retry up to 3 times with backoff before failing.
RUN set -eux; \
    for i in 1 2 3; do \
        apt-get update --fix-missing && break || { echo "apt-get update attempt $i failed; sleeping"; sleep $((i*5)); }; \
    done; \
    for i in 1 2 3; do \
        apt-get install -y --no-install-recommends \
            build-essential \
            curl \
            git \
            libpq-dev \
            ca-certificates \
        && break || { echo "apt-get install attempt $i failed; sleeping"; sleep $((i*5)); apt-get update --fix-missing; }; \
    done; \
    rm -rf /var/lib/apt/lists/*

# Install uv (fast resolver/installer)
RUN pip install --no-cache-dir "uv==0.2.24"

WORKDIR /app

# Copy only dependency descriptors first to maximize Docker layer caching.
COPY pyproject.toml requirements.txt README.md ./

# Install from requirements.txt (single source of truth; kept in sync with pyproject.toml
# for tool configs but with looser pins + Windows-friendly swaps where needed).
RUN uv pip install --system -r requirements.txt

# Then install the project itself (without re-resolving deps, since they're already in place).
COPY pfip ./pfip
RUN uv pip install --system --no-deps -e .

# Copy the rest of the source (alembic, tests, scripts). pfip/ was already copied.
# In dev, this whole dir is shadowed by a bind mount.
COPY . .

# FIX 17b: run as a non-root user instead of root. Create an unprivileged
# `appuser` and hand it ownership of the app dir (and the writable bind-mount
# target /app) so the dev bind-mount and any runtime writes still work.
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app

EXPOSE 8000

# FIX 17b: drop to the non-root user for all runtimes below.
USER appuser

# ---------------------------------------------------------------------------
# FIX 17c: PROD stage. Production build path — no --reload, no source bind-mount.
# Build & run with:
#   docker build --target prod -t pfip-backend:prod ../backend
#   # in compose, set the backend service's build.target to `prod` and REMOVE the
#   # `- ../backend:/app` bind-mount so the baked image is what actually runs.
# Runs as the same non-root appuser. Multiple workers, reload disabled.
# Defined BEFORE `dev` on purpose: with no build.target set, compose builds the
# LAST stage, so `dev` must stay last to keep the default behavior unchanged.
# ---------------------------------------------------------------------------
FROM base AS prod
CMD ["uvicorn", "pfip.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]

# ---------------------------------------------------------------------------
# DEV stage (DEFAULT target — must remain the last stage). The compose file
# mounts the source read-write so uvicorn --reload picks up edits. --reload and
# the RW bind-mount are DEV-ONLY; use the `prod` target above for production.
# ---------------------------------------------------------------------------
FROM base AS dev
CMD ["uvicorn", "pfip.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
