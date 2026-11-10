import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.v1.auth import router as auth_router
from app.api.v1.tasks import router as tasks_router
from app.core.config import Settings, get_settings
from app.core.constants import API_V1_PREFIX, APP_NAME, APP_VERSION
from app.core.exceptions import (
    AuthenticationException,
    ConflictException,
    DomainException,
    ForbiddenException,
    InvalidReferenceException,
    NotFoundException,
)
from app.database import Database
from app.schemas.base import ErrorResponse

logger = logging.getLogger("uvicorn.error.taskhub")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = app.state.settings or get_settings()
    settings.signing_key()
    app.state.settings = settings
    database = Database(settings)
    try:
        async with database.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        app.state.database = database
        logger.info("Starting %s", APP_NAME)
        yield
    finally:
        await database.close()
        logger.info("Stopping %s", APP_NAME)


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(
        title=APP_NAME,
        version=APP_VERSION,
        description="TaskHub: JWT authentication and protected async Task CRUD.",
        lifespan=lifespan,
    )

    app.state.settings = settings

    @app.exception_handler(NotFoundException)
    @app.exception_handler(ConflictException)
    @app.exception_handler(InvalidReferenceException)
    @app.exception_handler(AuthenticationException)
    @app.exception_handler(ForbiddenException)
    async def handle_domain_exception(
        request: Request, exc: DomainException
    ) -> JSONResponse:
        status_code = status.HTTP_404_NOT_FOUND
        if isinstance(exc, ConflictException):
            status_code = status.HTTP_409_CONFLICT
        elif isinstance(exc, InvalidReferenceException):
            status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
        elif isinstance(exc, AuthenticationException):
            status_code = status.HTTP_401_UNAUTHORIZED
        elif isinstance(exc, ForbiddenException):
            status_code = status.HTTP_403_FORBIDDEN
        return JSONResponse(
            status_code=status_code,
            content={"detail": exc.message},
            headers={"WWW-Authenticate": "Bearer"}
            if status_code == status.HTTP_401_UNAUTHORIZED
            else None,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = []
        for error in exc.errors():
            if "password" in error.get("loc", ()):
                error = {
                    key: value
                    for key, value in error.items()
                    if key not in {"input", "ctx"}
                }
            errors.append(error)
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"detail": jsonable_encoder(errors)},
        )

    app.include_router(auth_router, prefix=API_V1_PREFIX)
    app.include_router(
        tasks_router,
        prefix=API_V1_PREFIX,
        responses={
            status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
            status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        },
    )
    return app


app = create_app()
