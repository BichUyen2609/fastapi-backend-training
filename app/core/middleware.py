import logging
import re
from time import perf_counter
from uuid import uuid4

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.constants import (
    PROCESS_TIME_HEADER,
    REQUEST_ID_HEADER,
    SECURITY_HEADERS,
)

logger = logging.getLogger("taskhub.access")
REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]{8,64}")
MILLISECONDS = 1_000


def resolve_request_id(scope: Scope) -> str:
    for name, value in scope.get("headers", []):
        if name == REQUEST_ID_HEADER.lower().encode("latin-1"):
            candidate = bytes(value).decode("latin-1")
            if REQUEST_ID_PATTERN.fullmatch(candidate):
                return candidate
    return uuid4().hex


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = resolve_request_id(scope)
        scope.setdefault("state", {})["request_id"] = request_id
        started = perf_counter()
        status_code = 500

        async def send_with_context(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = MutableHeaders(scope=message)
                headers[REQUEST_ID_HEADER] = request_id
                headers[PROCESS_TIME_HEADER] = (
                    f"{(perf_counter() - started) * MILLISECONDS:.2f}"
                )
            await send(message)

        try:
            await self.app(scope, receive, send_with_context)
        finally:
            logger.info(
                "request_id=%s method=%s path=%s status=%s duration_ms=%.2f",
                request_id,
                scope["method"],
                scope["path"],
                status_code,
                (perf_counter() - started) * MILLISECONDS,
            )


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    headers.setdefault(name, value)
            await send(message)

        await self.app(scope, receive, send_with_headers)
