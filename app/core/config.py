from functools import lru_cache

from pydantic import PostgresDsn, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: PostgresDsn
    test_database_url: PostgresDsn | None = None
    database_echo: bool = False
    demo_email: str | None = None
    demo_password: SecretStr | None = None

    @field_validator("database_url", "test_database_url")
    @classmethod
    def require_async_driver(cls, value: PostgresDsn | None) -> PostgresDsn | None:
        if value is not None and value.scheme != "postgresql+asyncpg":
            raise ValueError("Use the postgresql+asyncpg driver")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
