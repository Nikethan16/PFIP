"""Application settings, loaded from environment variables.

All settings are read-only at runtime. Env vars mirror the names used in
`infra/docker-compose.yml` and `.env.example`.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from loguru import logger
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Global application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- App ---
    app_name: str = "pfip-backend"
    app_env: Literal["dev", "prod", "test"] = "dev"
    app_version: str = "0.1.0"
    # Headless data jobs (ingest/feature/regime pipeline, alembic) set this true.
    # They expose no login surface, so they don't require the web-auth secrets —
    # but real DB credentials are still enforced outside dev (see _validate_secrets).
    pipeline_mode: bool = Field(default=False, alias="PFIP_PIPELINE_MODE")

    # --- Auth ---
    nextauth_secret: str = Field(default="dev-change-me", alias="NEXTAUTH_SECRET")
    pfip_user_email: str = Field(default="user@example.com", alias="PFIP_USER_EMAIL")
    pfip_user_password_hash: str = Field(default="", alias="PFIP_USER_PASSWORD_HASH")
    jwt_algorithm: str = "HS256"
    jwt_access_token_ttl_minutes: int = 60 * 12  # 12h
    jwt_refresh_token_ttl_days: int = 30

    # --- Database ---
    database_url: str = Field(
        default="postgresql+psycopg://pfip:pfip_dev@timescaledb:5432/pfip",
        alias="DATABASE_URL",
    )
    # Async driver URL derived in property below.

    # --- Redis ---
    redis_url: str = Field(default="redis://redis:6379/0", alias="REDIS_URL")

    # --- Qdrant ---
    qdrant_url: str = Field(default="http://qdrant:6333", alias="QDRANT_URL")
    # Required by Qdrant Cloud (managed clusters reject unauthenticated calls);
    # leave blank for a local/unsecured Qdrant.
    qdrant_api_key: str = Field(default="", alias="QDRANT_API_KEY")

    # --- MLflow ---
    mlflow_tracking_uri: str = Field(default="http://mlflow:5000", alias="MLFLOW_TRACKING_URI")

    # --- Ollama ---
    ollama_host: str = Field(default="http://ollama:11434", alias="OLLAMA_HOST")

    # --- Prefect ---
    prefect_api_url: str = Field(default="http://prefect:4200/api", alias="PREFECT_API_URL")

    # --- LLM routing ---
    # Local default model (Ollama). All "sensitive" prompts route here.
    llm_default_model: str = Field(default="mistral:7b-instruct", alias="LLM_DEFAULT_MODEL")
    # Local embedding model fallback (Ollama). Overridden by NVIDIA NIM when
    # NVIDIA_NIM_API_KEY is set — see pfip/agent/embedder.py.
    llm_embed_model: str = Field(default="nomic-embed-text", alias="LLM_EMBED_MODEL")

    # --- Multi-provider LLM keys (all optional, all free-tier)             ---
    # The router (pfip/agent/router.py) decides where each task goes; keys
    # that are absent simply remove their providers from the fallback chain.
    groq_api_key: str = Field(default="", alias="GROQ_API_KEY")
    nvidia_nim_api_key: str = Field(default="", alias="NVIDIA_NIM_API_KEY")
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    deepseek_api_key: str = Field(default="", alias="DEEPSEEK_API_KEY")
    openrouter_api_key: str = Field(default="", alias="OPENROUTER_API_KEY")
    cohere_api_key: str = Field(default="", alias="COHERE_API_KEY")
    cerebras_api_key: str = Field(default="", alias="CEREBRAS_API_KEY")

    # Provider fallback chain priority order. The first provider that has a
    # key configured will be tried first for any cloud-routable task.
    llm_provider_priority: list[str] = Field(
        default_factory=lambda: ["groq", "gemini", "deepseek", "openrouter", "ollama"],
        alias="LLM_PROVIDER_PRIORITY",
    )

    # Strict-privacy mode: when True, anything classified Sensitive by
    # pfip.agent.privacy is hard-pinned to local Ollama, no override.
    llm_privacy_strict: bool = Field(default=True, alias="LLM_PRIVACY_STRICT")

    # Per-request LLM timeout (seconds). Passed to every litellm call so a
    # hung local Ollama can't block the SSE stream forever.
    llm_request_timeout_s: float = Field(default=120.0, alias="LLM_REQUEST_TIMEOUT_S")

    # LangSmith tracing (optional; enables LLM call traces).
    langsmith_api_key: str = Field(default="", alias="LANGSMITH_API_KEY")
    langsmith_project: str = Field(default="pfip", alias="LANGSMITH_PROJECT")
    langsmith_tracing: bool = Field(default=False, alias="LANGSMITH_TRACING")

    # --- Risk / portfolio defaults ---
    max_position_pct: float = Field(default=0.10, alias="MAX_POSITION_PCT")
    drawdown_halt_pct: float = Field(default=0.20, alias="DRAWDOWN_HALT_PCT")
    daily_new_positions_cap: int = Field(default=2, alias="DAILY_NEW_POSITIONS_CAP")
    paper_starting_capital_inr: float = Field(
        default=1_000_000.0, alias="PAPER_STARTING_CAPITAL_INR"
    )

    # --- Tax / locale ---
    tax_year_start: str = Field(default="2026-04-01", alias="TAX_YEAR_START")
    tax_year_end: str = Field(default="2027-03-31", alias="TAX_YEAR_END")
    home_currency: str = Field(default="INR", alias="HOME_CURRENCY")

    # --- Feature flags ---
    feature_ml_signals: bool = Field(default=False, alias="FEATURE_ML_SIGNALS")
    feature_shadow_portfolio: bool = Field(default=True, alias="FEATURE_SHADOW_PORTFOLIO")
    feature_morning_brief: bool = Field(default=True, alias="FEATURE_MORNING_BRIEF")

    # --- CORS ---
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # --- Observability ---
    sentry_dsn: str = Field(default="", alias="SENTRY_DSN")

    @model_validator(mode="after")
    def _validate_secrets(self) -> "Settings":
        """Fail loudly when running outside dev with insecure defaults.

        In ``dev`` (and ``test``) we tolerate the defaults but emit a loud
        warning so the operator knows the deployment is not production-safe.
        In any other env (``prod``) an insecure default is a hard ValueError
        at startup.
        """
        insecure: list[str] = []
        # Web-auth secrets only matter when the API/login surface is exposed.
        # Headless pipeline jobs (PFIP_PIPELINE_MODE=true) never authenticate a
        # user, so requiring these would block ingest/alembic for no security gain.
        if not self.pipeline_mode:
            if self.nextauth_secret in ("", "dev-change-me"):
                insecure.append("NEXTAUTH_SECRET is unset or still the dev default")
            if self.pfip_user_password_hash == "":
                insecure.append("PFIP_USER_PASSWORD_HASH is empty")
        # DB credentials must always be real outside dev — pipeline jobs included.
        if "pfip:pfip_dev" in self.database_url:
            insecure.append("DATABASE_URL still contains the default pfip:pfip_dev credentials")

        if not insecure:
            return self

        detail = "; ".join(insecure)
        if self.app_env == "dev":
            logger.warning(
                f"INSECURE CONFIG (allowed in dev only): {detail}. "
                "Set real secrets before deploying outside dev."
            )
            return self
        raise ValueError(
            f"Refusing to start in app_env={self.app_env!r} with insecure defaults: {detail}."
        )

    @property
    def database_url_async(self) -> str:
        """SQLAlchemy async URL (psycopg v3 supports both sync and async via one driver).

        We accept the sync form in env but route SQLAlchemy through `postgresql+psycopg`
        which supports async. If users supply `postgresql://` we rewrite it.
        """
        url = self.database_url
        if url.startswith("postgresql+psycopg://"):
            return url
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+psycopg://", 1)
        return url

    @property
    def database_url_sync(self) -> str:
        """Alembic uses the sync URL."""
        url = self.database_url
        if url.startswith("postgresql+psycopg://"):
            return url.replace("postgresql+psycopg://", "postgresql+psycopg://", 1)
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+psycopg://", 1)
        return url


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()
