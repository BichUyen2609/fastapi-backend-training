import asyncio
import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx2 import ASGITransport, AsyncClient
from pydantic import SecretStr, ValidationError
from redis.asyncio import Redis
from redis.exceptions import ConnectionError
from sqlalchemy.exc import OperationalError

from app.core.cache import TaskCache
from app.core.config import Settings, get_settings
from app.core.logging import (
    JsonFormatter,
    TextFormatter,
    configure_logging,
    request_id_context,
)
from app.database import Database
from app.main import create_app

pytestmark = pytest.mark.anyio


def test_example_configuration_validates_with_generated_signing_key(
    test_settings: Settings,
) -> None:
    settings = Settings(
        _env_file=Path(__file__).resolve().parents[1] / ".env.example",
        jwt_secret=test_settings.jwt_secret,
    )
    assert settings.notifications_enabled
    assert settings.smtp_sender == "notifications@example.com"


@pytest.mark.parametrize(
    "overrides",
    [
        {"environment": "../production"},
        {"environment": "staging"},
        {"log_level": "VERBOSE"},
        {"log_format": "xml"},
        {"smtp_port": 0},
        {"smtp_timeout_seconds": 0},
        {"smtp_sender": "invalid-address"},
        {"notifications_enabled": True, "smtp_host": None, "smtp_sender": None},
        {"notifications_enabled": True, "smtp_host": "localhost", "smtp_sender": None},
        {"environment": "production", "database_echo": True},
        {"environment": "production", "cors_origins": ["*"]},
    ],
)
def test_invalid_environment_configuration_fails_fast(
    test_settings: Settings, overrides: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate(test_settings.model_dump() | overrides)


def test_smtp_credentials_are_paired_and_production_requires_tls(
    test_settings: Settings,
) -> None:
    configuration = test_settings.model_dump() | {
        "notifications_enabled": True,
        "smtp_host": "smtp.example.com",
        "smtp_sender": "notifications@example.com",
        "smtp_username": "smtp-user",
        "smtp_password": SecretStr("smtp-password-private"),
    }
    with pytest.raises(ValidationError, match="set together"):
        Settings.model_validate(configuration | {"smtp_password": None})
    with pytest.raises(ValidationError, match="STARTTLS or SSL"):
        Settings.model_validate(configuration | {"environment": "production"})
    for security in ("starttls", "ssl"):
        settings = Settings.model_validate(
            configuration | {"environment": "production", "smtp_security": security}
        )
        assert settings.smtp_security == security
        assert "smtp-password-private" not in repr(settings)


def test_environment_files_and_process_variable_precedence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, test_settings: Settings
) -> None:
    for field in Settings.model_fields:
        monkeypatch.delenv(field.upper(), raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        f"DATABASE_URL={test_settings.database_url}\nENVIRONMENT=testing\nLOG_LEVEL=INFO\n",
        encoding="utf-8",
    )
    (tmp_path / ".env.testing").write_text("LOG_LEVEL=WARNING\n", encoding="utf-8")
    (tmp_path / ".env.production").write_text("LOG_LEVEL=ERROR\n", encoding="utf-8")
    try:
        get_settings.cache_clear()
        assert get_settings().log_level == "WARNING"
        monkeypatch.setenv("LOG_LEVEL", "CRITICAL")
        get_settings.cache_clear()
        assert get_settings().log_level == "CRITICAL"
        monkeypatch.delenv("LOG_LEVEL")
        monkeypatch.setenv("ENVIRONMENT", "production")
        get_settings.cache_clear()
        assert get_settings().environment == "production"
        assert get_settings().log_level == "ERROR"
    finally:
        get_settings.cache_clear()


async def test_health_probes_are_public(client: AsyncClient) -> None:
    client.headers.pop("Authorization")
    assert (await client.get("/health/live")).json() == {"status": "ok"}
    response = await client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "database": "up",
        "cache": "disabled",
    }


async def test_database_readiness_failure_is_503_without_internal_details(
    application: FastAPI, client: AsyncClient
) -> None:
    database: Database = application.state.database
    failure = OperationalError("private SQL", {}, OSError("private password"))
    with patch.object(type(database.engine), "connect", side_effect=failure):
        response = await client.get("/health/ready")
        assert (await client.get("/health/live")).status_code == 200
    assert response.status_code == 503
    assert response.headers["retry-after"] == "5"
    assert response.json()["code"] == "SERVICE_UNAVAILABLE"
    assert "private" not in response.text


@pytest.mark.parametrize("available", [True, False])
async def test_readiness_reports_optional_cache_without_blocking_api(
    application: FastAPI, client: AsyncClient, available: bool
) -> None:
    cache: TaskCache = application.state.task_cache
    redis = AsyncMock(spec=Redis)
    redis.ping = AsyncMock(return_value=True)
    if not available:
        redis.ping.side_effect = ConnectionError("Redis unavailable")
    with patch.object(cache, "client", redis):
        response = await client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["cache"] == ("up" if available else "unavailable")


async def test_api_documentation_can_be_disabled(test_settings: Settings) -> None:
    app = create_app(
        Settings.model_validate(test_settings.model_dump() | {"docs_enabled": False})
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert (await client.get(path)).status_code == 404
        assert (await client.get("/health/live")).status_code == 200


async def test_openapi_groups_operations_and_documents_common_errors(
    client: AsyncClient,
) -> None:
    document = (await client.get("/openapi.json")).json()
    assert {tag["name"] for tag in document["tags"]} == {
        "Authentication",
        "Users",
        "Workspaces",
        "Projects",
        "Tasks",
        "Labels",
        "Comments",
        "Health",
    }
    for path, operations in document["paths"].items():
        for operation in operations.values():
            for status in ("422", "500", "503"):
                response = operation["responses"][status]
                assert response["content"]["application/json"]["schema"][
                    "$ref"
                ].endswith("/ErrorResponse")
                assert (
                    "request_id" in response["content"]["application/json"]["example"]
                )
            if path.startswith("/health/"):
                assert not operation.get("security")


async def test_concurrent_request_contexts_do_not_leak(
    application: FastAPI, client: AsyncClient
) -> None:
    async def context() -> dict[str, str | None]:
        await asyncio.sleep(0)
        return {"request_id": request_id_context.get()}

    application.add_api_route("/test/context", context)
    identifiers = [f"concurrent-{index:04d}" for index in range(10)]
    responses = await asyncio.gather(
        *[
            client.get("/test/context", headers={"X-Request-ID": value})
            for value in identifiers
        ]
    )
    assert [response.json()["request_id"] for response in responses] == identifiers
    assert request_id_context.get() is None


def test_json_logs_are_utc_correlated_and_omit_exception_values() -> None:
    try:
        raise RuntimeError("smtp-password-private")
    except RuntimeError:
        record = logging.LogRecord(
            "taskhub.test",
            logging.ERROR,
            __file__,
            1,
            "Request failed",
            (),
            sys.exc_info(),
        )
    token = request_id_context.set("logging-request-0001")
    try:
        output = JsonFormatter().format(record)
        payload = json.loads(output)
        assert payload["request_id"] == "logging-request-0001"
        assert payload["exception_type"] == "RuntimeError"
        assert payload["stack"]
        assert "smtp-password-private" not in output
        assert datetime.fromisoformat(payload["timestamp"]).utcoffset() == timedelta(0)
    finally:
        request_id_context.reset(token)


def test_text_formatter_keeps_each_event_on_one_line() -> None:
    record = logging.LogRecord(
        "taskhub.test", logging.INFO, __file__, 1, "a\r\nb", (), None
    )
    assert "\n" not in TextFormatter().format(record)


async def test_unhandled_error_keeps_structured_request_id_after_context_reset(
    application: FastAPI, client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    async def explode() -> None:
        raise RuntimeError("private error value")

    application.add_api_route("/test/log-error", explode)
    async with AsyncClient(
        transport=ASGITransport(app=application, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as raw:
        with caplog.at_level(logging.ERROR, logger="taskhub.errors"):
            response = await raw.get(
                "/test/log-error", headers={"X-Request-ID": "structured-error-0001"}
            )
    assert response.status_code == 500
    record = next(
        record for record in caplog.records if record.name == "taskhub.errors"
    )
    payload = json.loads(JsonFormatter().format(record))
    assert payload["request_id"] == "structured-error-0001"
    assert "private error value" not in json.dumps(payload)


@pytest.mark.parametrize("format_name", ["json", "text"])
def test_logging_configuration_is_idempotent(
    test_settings: Settings, format_name: str
) -> None:
    logger = logging.Logger("isolated")
    settings = Settings.model_validate(
        test_settings.model_dump() | {"log_format": format_name, "log_level": "WARNING"}
    )
    with patch("app.core.logging.logging.getLogger", return_value=logger):
        configure_logging(settings)
        configure_logging(settings)
    assert len(logger.handlers) == 1
    assert logger.level == logging.WARNING
    assert isinstance(
        logger.handlers[0].formatter,
        JsonFormatter if format_name == "json" else TextFormatter,
    )
