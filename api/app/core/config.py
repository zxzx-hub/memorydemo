"""Environment-backed application configuration."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from MEMORY_* environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="MEMORY_",
        extra="ignore",
        frozen=True,
    )

    app_name: str = "agent-memory-service"
    environment: str = "development"
    log_level: str = "INFO"
    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)
    database_url: str = "postgresql+asyncpg://memory:memory@localhost:5432/memory"
    redis_url: str = "redis://localhost:6379/0"
    readiness_timeout_seconds: float = Field(default=2.0, gt=0, le=30)
    enable_development_tenant_resolver: bool = False
    consolidation_message_count: int = Field(default=10, ge=1)
    consolidation_token_ratio: float = Field(default=0.7, gt=0, le=1)
    consolidation_idle_seconds: int = Field(default=600, ge=1)
    working_memory_ttl_seconds: int = Field(default=86400, ge=60)
    retrieval_semantic_weight: float = Field(default=0.35, ge=0)
    retrieval_confidence_weight: float = Field(default=0.15, ge=0)
    retrieval_importance_weight: float = Field(default=0.15, ge=0)
    retrieval_explicitness_weight: float = Field(default=0.10, ge=0)
    retrieval_freshness_weight: float = Field(default=0.10, ge=0)
    retrieval_usage_weight: float = Field(default=0.05, ge=0)
    retrieval_scope_weight: float = Field(default=0.10, ge=0)
    retrieval_freshness_half_life_days: float = Field(default=180, gt=0)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide immutable settings object."""

    return Settings()
