from pydantic_settings import BaseSettings, SettingsConfigDict


class APISettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="API_", env_file=".env", extra="ignore"
    )


api_settings = APISettings()
