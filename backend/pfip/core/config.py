"""Application settings, loaded from environment variables.

All settings are read-only at runtime. Env vars mirror the names used in
`infra/docker-compose.yml` and `.env.example`.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
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

    # --- MLflow ---
    mlflow_tracking_uri: str = Field(default="http://mlflow:5000", alias="MLFLOW_TRACKING_URI")

    # --- Ollama ---
    ollama_host: str = Field(default="http://ollama:11434", alias="OLLAMA_HOST")

    # --- Prefect ---
    prefect_api_url: str = Field(default="http://prefect:4200/api", alias="PREFECT_API_URL")

    # --- LLM routing ---
    llm_default_model: str = Field(default="mistral:7b-instruct", alias="LLM_DEFAULT_MODEL")
    llm_embed_model: str = Field(default="nomic-embed-text", alias="LLM_EMBED_MODEL")

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
