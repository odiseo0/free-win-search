from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class SearchSettings(BaseSettings):
    backend: Literal["postgresql", "meilisearch"] = "postgresql"
    meilisearch_url: str | None = None
    meilisearch_api_key: SecretStr | None = None
    index_uid: str = Field(default="cards", min_length=1)
    timeout_seconds: float = Field(default=5.0, gt=0)
    max_connections: int = Field(default=20, ge=1)
    max_concurrency: int = Field(default=10, ge=1)
    max_retries: int = Field(default=2, ge=0)
    retry_backoff_seconds: float = Field(default=0.1, ge=0)
    max_retry_delay_seconds: float = Field(default=5.0, ge=0)
    task_timeout_seconds: float = Field(default=30.0, gt=0)
    task_poll_interval_seconds: float = Field(default=0.1, gt=0)
    outbox_batch_size: int = Field(default=100, ge=1, le=1000)
    outbox_lease_seconds: int = Field(default=60, ge=1)
    outbox_poll_seconds: float = Field(default=2.0, gt=0)
    outbox_backoff_seconds: int = Field(default=5, ge=1)

    model_config = SettingsConfigDict(
        env_prefix="SEARCH_", env_file=".env", extra="ignore"
    )


search_settings = SearchSettings()
