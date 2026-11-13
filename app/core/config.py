from functools import lru_cache

from pydantic import Field, PostgresDsn, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.constants import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    JWT_SECRET_MIN_BYTES,
    MAX_ACCESS_TOKEN_EXPIRE_MINUTES,
    MAX_REFRESH_TOKEN_EXPIRE_DAYS,
    REFRESH_TOKEN_EXPIRE_DAYS,
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    database_url: PostgresDsn
    test_database_url: PostgresDsn | None = None
    database_echo: bool = False
    demo_email: str | None = None
    demo_password: SecretStr | None = None
    jwt_secret: SecretStr | None = None
    jwt_issuer: str = "taskhub"
    jwt_audience: str = "taskhub-api"
    access_token_expire_minutes: int = Field(
        default=ACCESS_TOKEN_EXPIRE_MINUTES, ge=1, le=MAX_ACCESS_TOKEN_EXPIRE_MINUTES
    )
    refresh_token_expire_days: int = Field(
        default=REFRESH_TOKEN_EXPIRE_DAYS, ge=1, le=MAX_REFRESH_TOKEN_EXPIRE_DAYS
    )

    @field_validator("jwt_secret")
    @classmethod
    def validate_signing_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None:
            key = value.get_secret_value()
            if len(key.encode("utf-8")) < JWT_SECRET_MIN_BYTES or key.startswith(
                "change-"
            ):
                raise ValueError(
                    "JWT_SECRET must be a generated key of at least 32 bytes"
                )
        return value

    def signing_key(self) -> str:
        if self.jwt_secret is None:
            raise ValueError("Set JWT_SECRET before starting the API")
        return self.jwt_secret.get_secret_value()

    @field_validator("database_url", "test_database_url")
    @classmethod
    def require_async_driver(cls, value: PostgresDsn | None) -> PostgresDsn | None:
        if value is not None and value.scheme != "postgresql+asyncpg":
            raise ValueError("Use the postgresql+asyncpg driver")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
