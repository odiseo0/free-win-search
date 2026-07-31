from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ScraperSettings(BaseSettings):
    poll_seconds: float = Field(default=2.0, gt=0)
    lease_seconds: int = Field(default=180, gt=0)
    max_attempts: int = Field(default=4, ge=1)
    retry_delays_seconds: tuple[int, ...] = (60, 300, 900, 3600)
    concurrency: int = Field(default=5, ge=1)
    http_timeout_seconds: float = Field(default=15.0, gt=0)
    min_host_interval_seconds: float = Field(default=0.25, ge=0)
    backfill_state_path: Path = Path("var/scraper/missing-listings-backfill.json")
    backfill_batch_size: int = Field(default=50, ge=1, le=50)
    backfill_min_interval_minutes: int = Field(default=5, ge=1)
    backfill_max_interval_minutes: int = Field(default=30, ge=1)
    backfill_priority: int = -10

    model_config = SettingsConfigDict(
        env_prefix="SCRAPER_",
        env_file=".env",
        extra="ignore",
    )


scraper_settings = ScraperSettings()
