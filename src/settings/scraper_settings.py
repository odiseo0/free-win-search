from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ScraperCookieSettings(BaseModel):
    name: str = Field(min_length=1)
    value: SecretStr
    domain: str = "www.coolstuffinc.com"
    path: str = "/"
    expires_at: datetime | None = None

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, value: str) -> str:
        if value.casefold() != "www.coolstuffinc.com":
            raise ValueError("Scraper cookies must target www.coolstuffinc.com")

        return value.casefold()

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        if value != "/":
            raise ValueError("Scraper cookie path must be /")

        return value

    @field_validator("expires_at")
    @classmethod
    def validate_expiration(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("Scraper cookie expiration must include a timezone")

        return value


class ScraperSettings(BaseSettings):
    poll_seconds: float = Field(default=2.0, gt=0)
    lease_seconds: int = Field(default=180, gt=0)
    max_attempts: int = Field(default=4, ge=1)
    retry_delays_seconds: tuple[int, ...] = (60, 300, 900, 3600)
    concurrency: int = Field(default=5, ge=1)
    http_timeout_seconds: float = Field(default=15.0, gt=0)
    min_host_interval_seconds: float = Field(default=0.25, ge=0)
    cookies: tuple[ScraperCookieSettings, ...] = ()
    max_search_pages: int = Field(default=10, ge=1, le=50)
    job_timeout_seconds: float = Field(default=150.0, gt=0)
    backfill_state_path: Path = Path("var/scraper/missing-listings-backfill.json")
    backfill_batch_size: int = Field(default=50, ge=1, le=50)
    backfill_min_interval_minutes: int = Field(default=5, ge=1)
    backfill_max_interval_minutes: int = Field(default=30, ge=1)
    backfill_priority: int = -10

    @field_validator("cookies")
    @classmethod
    def validate_unique_cookie_names(
        cls, value: tuple[ScraperCookieSettings, ...]
    ) -> tuple[ScraperCookieSettings, ...]:
        names = [cookie.name for cookie in value]

        if len(names) != len(set(names)):
            raise ValueError("Scraper cookie names must be unique")

        return value

    @model_validator(mode="after")
    def validate_job_timeout(self) -> "ScraperSettings":
        if self.job_timeout_seconds >= self.lease_seconds:
            raise ValueError("Scraper job timeout must be shorter than its lease")

        return self

    model_config = SettingsConfigDict(
        env_prefix="SCRAPER_",
        env_file=".env",
        extra="ignore",
    )


scraper_settings = ScraperSettings()
