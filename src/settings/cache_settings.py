from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class CacheSettings(BaseSettings):
    backend: Literal["memory", "valkey"] = "memory"
    url: SecretStr = SecretStr("valkey://localhost:6379/0")
    key_prefix: str = Field(default="free-win:", min_length=1)
    socket_timeout_seconds: float = Field(default=2.0, gt=0)
    socket_connect_timeout_seconds: float = Field(default=2.0, gt=0)

    model_config = SettingsConfigDict(
        env_prefix="CACHE_",
        env_file=".env",
        extra="ignore",
    )

    @field_validator("url")
    @classmethod
    def validate_url_scheme(cls, url: SecretStr) -> SecretStr:
        supported_schemes = ("valkey://", "valkeys://", "unix://")

        if not url.get_secret_value().startswith(supported_schemes):
            raise ValueError("CACHE_URL must use valkey://, valkeys:// or unix://")

        return url


cache_settings = CacheSettings()
