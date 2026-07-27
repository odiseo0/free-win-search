from typing import ClassVar

from pydantic_settings import BaseSettings, SettingsConfigDict


class StorageSettings(BaseSettings):
    STORAGE_KEY: str | None = None
    STORAGE_SECRET: str | None = None
    STORAGE_ENDPOINT: str | None = None
    STORAGE_BUCKET: str | None = None
    STORAGE_REGION: str | None = None

    model_config: ClassVar[SettingsConfigDict] = {"env_file": ".env", "extra": "ignore"}


storage_settings = StorageSettings()
