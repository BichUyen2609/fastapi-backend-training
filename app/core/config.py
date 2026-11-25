from functools import lru_cache
from typing import Literal, Self

from pydantic import (
    EmailStr,
    Field,
    PostgresDsn,
    RedisDsn,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.constants import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    JWT_SECRET_MIN_BYTES,
    MAX_ACCESS_TOKEN_EXPIRE_MINUTES,
    MAX_CACHE_TTL_SECONDS,
    MAX_REFRESH_TOKEN_EXPIRE_DAYS,
    REDIS_TIMEOUT_SECONDS,
    REFRESH_TOKEN_EXPIRE_DAYS,
    TASK_CACHE_NAMESPACE,
    TASK_CACHE_TTL_SECONDS,
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    database_url: PostgresDsn
    environment: Literal["development", "testing", "production"] = "development"
    docs_enabled: bool = True
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_format: Literal["json", "text"] = "json"
    notifications_enabled: bool = False
    smtp_host: str | None = Field(default=None, min_length=1)
    smtp_port: int = Field(default=1025, ge=1, le=65_535)
    smtp_sender: EmailStr | None = None
    smtp_username: str | None = Field(default=None, repr=False)
    smtp_password: SecretStr | None = None
    smtp_security: Literal["none", "starttls", "ssl"] = "none"
    smtp_timeout_seconds: float = Field(default=5, gt=0, le=30)
    test_database_url: PostgresDsn | None = None
    database_echo: bool = False
    redis_url: RedisDsn | None = Field(default=None, repr=False)
    test_redis_url: RedisDsn | None = Field(default=None, repr=False)
    cache_ttl_seconds: int = Field(
        default=TASK_CACHE_TTL_SECONDS, gt=0, le=MAX_CACHE_TTL_SECONDS
    )
    cache_namespace: str = Field(
        default=TASK_CACHE_NAMESPACE, pattern=r"^[A-Za-z0-9_-]{1,64}$"
    )
    redis_timeout_seconds: float = Field(default=REDIS_TIMEOUT_SECONDS, gt=0, le=5)
    demo_email: str | None = None
    demo_password: SecretStr | None = None
    jwt_secret: SecretStr | None = None
    jwt_issuer: str = "taskhub"
    jwt_audience: str = "taskhub-api"
    access_token_expire_minutes: int = Field(
        default=ACCESS_TOKEN_EXPIRE_MINUTES, ge=1, le=MAX_ACCESS_TOKEN_EXPIRE_MINUTES
    )
    cors_origins: list[str] = Field(default_factory=list)
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

    @field_validator("smtp_username", "smtp_password", mode="before")
    @classmethod
    def empty_smtp_credential(cls, value: object) -> object:
        return None if value == "" else value

    @model_validator(mode="after")
    def validate_environment(self) -> Self:
        if self.notifications_enabled:
            if self.smtp_host is None or self.smtp_sender is None:
                raise ValueError(
                    "Set SMTP_HOST and SMTP_SENDER to enable notifications"
                )
            if (self.smtp_username is None) != (self.smtp_password is None):
                raise ValueError("SMTP_USERNAME and SMTP_PASSWORD must be set together")
        if self.environment == "production":
            if self.database_echo or "*" in self.cors_origins:
                raise ValueError(
                    "Production requires DATABASE_ECHO=false and explicit CORS origins"
                )
            if self.notifications_enabled and self.smtp_security == "none":
                raise ValueError("Production SMTP requires STARTTLS or SSL")
        return self

    @field_validator("database_url", "test_database_url")
    @classmethod
    def require_async_driver(cls, value: PostgresDsn | None) -> PostgresDsn | None:
        if value is not None and value.scheme != "postgresql+asyncpg":
            raise ValueError("Use the postgresql+asyncpg driver")
        return value


class EnvironmentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: Literal["development", "testing", "production"] = "development"


@lru_cache
def get_settings() -> Settings:
    environment = EnvironmentSettings().environment
    return Settings(_env_file=(".env", f".env.{environment}"), environment=environment)
