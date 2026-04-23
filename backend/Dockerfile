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
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        git \
        libpq-dev \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

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

EXPOSE 8000

# The compose file mounts the source read-write so --reload picks up edits.
CMD ["uvicorn", "pfip.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
