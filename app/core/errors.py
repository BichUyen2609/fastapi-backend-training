import logging
from collections.abc import Mapping
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.constants import INTERNAL_ERROR, REQUEST_ID_HEADER, SERVICE_UNAVAILABLE
from app.core.exceptions import DomainException

logger = logging.getLogger("taskhub.errors")
SENSITIVE_FIELDS = ("password", "token")


def is_sensitive(location: object) -> bool:
    return isinstance(location, list | tuple) and any(
        isinstance(part, str) and any(word in part for word in SENSITIVE_FIELDS)
        for part in location
    )


def status_code_name(status_code: int) -> str:
    try:
        return HTTPStatus(status_code).name
    except ValueError:
        return f"HTTP_{status_code}"


def error_response(
    request: Request,
    status_code: int,
    detail: Any,
    code: str,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    request_id: str | None = getattr(request.state, "request_id", None)
    response_headers = dict(headers or {})
    if request_id is not None:
        response_headers[REQUEST_ID_HEADER] = request_id
    if status_code == status.HTTP_401_UNAUTHORIZED:
        response_headers.setdefault("WWW-Authenticate", "Bearer")
    return JSONResponse(
        status_code=status_code,
        content={"detail": detail, "code": code, "request_id": request_id},
        headers=response_headers,
    )


async def handle_domain_exception(
    request: Request, exc: DomainException
) -> JSONResponse:
    return error_response(request, exc.status_code, exc.message, exc.code)


async def handle_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    errors = [
        {key: value for key, value in error.items() if key not in {"input", "ctx"}}
        if is_sensitive(error.get("loc", ()))
        else error
        for error in exc.errors()
    ]
    return error_response(
        request,
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        jsonable_encoder(errors),
        "VALIDATION_ERROR",
    )


async def handle_http_exception(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    return error_response(
        request,
        exc.status_code,
        exc.detail,
        status_code_name(exc.status_code),
        exc.headers,
    )


async def handle_database_unavailable(
    request: Request, exc: DBAPIError
) -> JSONResponse:
    logger.error(
        "Database unavailable request_id=%s error=%s",
        getattr(request.state, "request_id", None),
        type(exc.orig).__name__,
    )
    return error_response(
        request,
        status.HTTP_503_SERVICE_UNAVAILABLE,
        SERVICE_UNAVAILABLE,
        "SERVICE_UNAVAILABLE",
        {"Retry-After": "5"},
    )


async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(
        "Unhandled error request_id=%s method=%s path=%s",
        getattr(request.state, "request_id", None),
        request.method,
        request.url.path,
        exc_info=exc,
    )
    return error_response(
        request,
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        INTERNAL_ERROR,
        "INTERNAL_ERROR",
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.exception_handler(DomainException)(handle_domain_exception)
    app.exception_handler(RequestValidationError)(handle_validation_error)
    app.exception_handler(StarletteHTTPException)(handle_http_exception)
    app.exception_handler(OperationalError)(handle_database_unavailable)
    app.exception_handler(Exception)(handle_unexpected_error)
