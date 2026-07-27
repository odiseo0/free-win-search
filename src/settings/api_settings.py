from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class APISettings(BaseSettings):
    environment: Literal["development", "test", "production"] = "development"

    model_config = SettingsConfigDict(
        env_prefix="API_", env_file=".env", extra="ignore"
    )


api_settings = APISettings()
