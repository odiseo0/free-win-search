from pydantic import ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DBSettings(BaseSettings):
    DB_HOST: str | None = None
    DB_NAME: str | None = None
    DB_PORT: int | None = None
    DB_USERNAME: str | None = None
    DB_PASSWORD: str | None = None

    SQLALCHEMY_DATABASE_URI: str | None = None
    pool_size: int = 5
    pool_timeout: int = 30
    pool_recycle: int = 1800
    pool_overflow: int = 10

    @field_validator("SQLALCHEMY_DATABASE_URI", mode="before")
    def assemble_db_connection(cls, v: str | None, info: ValidationInfo) -> str:
        if isinstance(v, str):
            return v

        return f"postgresql+asyncpg://{info.data['DB_USERNAME']}:{info.data['DB_PASSWORD']}@{info.data['DB_HOST']}:{info.data['DB_PORT']}/{info.data['DB_NAME']}"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


db_settings = DBSettings()
