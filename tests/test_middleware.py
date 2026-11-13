import logging
from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy.exc import OperationalError

from app.core.config import Settings
from app.main import create_app

pytestmark = pytest.mark.anyio


@pytest.fixture
async def raw_client(
    application: FastAPI, client: AsyncClient
) -> AsyncIterator[AsyncClient]:
    async def explode() -> None:
        raise RuntimeError("database password leaked")

    async def database_down() -> None:
        raise OperationalError("SELECT 1", {}, ConnectionRefusedError())

    application.add_api_route("/test/explode", explode)
    application.add_api_route("/test/database-down", database_down)
    async with AsyncClient(
        transport=ASGITransport(app=application, raise_app_exceptions=False),
        base_url="http://testserver",
        headers={"Authorization": client.headers["Authorization"]},
    ) as test_client:
        yield test_client


async def test_request_id_is_generated_and_echoed(client: AsyncClient) -> None:
    response = await client.get("/api/v1/users/me")
    generated = response.headers["x-request-id"]
    assert len(generated) == 32
    assert float(response.headers["x-process-time-ms"]) >= 0
    supplied = await client.get(
        "/api/v1/users/me", headers={"X-Request-ID": "client-trace-0001"}
    )
    assert supplied.headers["x-request-id"] == "client-trace-0001"


@pytest.mark.parametrize("value", ["short", "has space here", "x" * 65, "bad\\id12"])
async def test_untrusted_request_id_is_replaced(
    client: AsyncClient, value: str
) -> None:
    response = await client.get("/api/v1/users/me", headers={"X-Request-ID": value})
    assert response.headers["x-request-id"] != value
    assert len(response.headers["x-request-id"]) == 32


async def test_security_headers_are_added(client: AsyncClient) -> None:
    response = await client.get("/api/v1/users/me")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"


async def test_errors_share_one_shape_with_request_id(client: AsyncClient) -> None:
    missing = await client.get(
        "/api/v1/tasks/2000000000", headers={"X-Request-ID": "trace-missing-1"}
    )
    assert missing.status_code == 404
    assert missing.json() == {
        "detail": "Task not found",
        "code": "NOT_FOUND",
        "request_id": "trace-missing-1",
    }
    route = await client.get("/api/v1/does-not-exist")
    assert route.status_code == 404
    assert route.json()["code"] == "NOT_FOUND"
    assert route.json()["request_id"] == route.headers["x-request-id"]
    method = await client.put("/api/v1/users/me")
    assert method.status_code == 405
    assert method.json()["code"] == "METHOD_NOT_ALLOWED"
    invalid = await client.get("/api/v1/tasks", params={"page": 0})
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "VALIDATION_ERROR"
    assert isinstance(invalid.json()["detail"], list)
    client.headers.pop("Authorization")
    unauthorized = await client.get("/api/v1/users/me")
    assert unauthorized.json()["code"] == "UNAUTHORIZED"
    assert unauthorized.headers["www-authenticate"] == "Bearer"


async def test_unhandled_error_is_500_without_leaking_details(
    raw_client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR, logger="taskhub.errors"):
        response = await raw_client.get(
            "/test/explode", headers={"X-Request-ID": "trace-explode-1"}
        )
    assert response.status_code == 500
    assert response.json() == {
        "detail": "Internal server error",
        "code": "INTERNAL_ERROR",
        "request_id": "trace-explode-1",
    }
    assert "password" not in response.text
    assert response.headers["x-request-id"] == "trace-explode-1"
    assert any("trace-explode-1" in record.getMessage() for record in caplog.records)


async def test_database_outage_is_503(raw_client: AsyncClient) -> None:
    response = await raw_client.get("/test/database-down")
    assert response.status_code == 503
    assert response.json()["code"] == "SERVICE_UNAVAILABLE"
    assert response.headers["retry-after"] == "5"
    assert "SELECT" not in response.text


async def test_access_log_records_request(
    client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="taskhub.access"):
        await client.get("/api/v1/users/me", headers={"X-Request-ID": "trace-log-0001"})
    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "request_id=trace-log-0001" in message
        and "path=/api/v1/users/me" in message
        and "status=200" in message
        for message in messages
    )
    assert not any("Bearer" in message for message in messages)


async def test_cors_allows_only_configured_origins(test_settings: Settings) -> None:
    settings = Settings.model_validate(
        test_settings.model_dump() | {"cors_origins": ["http://localhost:3000"]}
    )
    app = create_app(settings)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as cors_client:
        allowed = await cors_client.options(
            "/api/v1/tasks",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert allowed.status_code == 200
        assert allowed.headers["access-control-allow-origin"] == "http://localhost:3000"
        denied = await cors_client.options(
            "/api/v1/tasks",
            headers={
                "Origin": "http://evil.example",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert "access-control-allow-origin" not in denied.headers
