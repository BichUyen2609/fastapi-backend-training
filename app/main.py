import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.params import PROTECTED_ERRORS
from app.api.v1.auth import router as auth_router
from app.api.v1.projects import router as projects_router
from app.api.v1.tasks import router as tasks_router
from app.api.v1.users import router as users_router
from app.api.v1.workspaces import router as workspaces_router
from app.core.config import Settings, get_settings
from app.core.constants import API_V1_PREFIX, APP_NAME, APP_VERSION
from app.core.exceptions import (
    AuthenticationException,
    BadRequestException,
    ConflictException,
    DomainException,
    ForbiddenException,
    InvalidReferenceException,
    NotFoundException,
)
from app.database import Database

logger = logging.getLogger("uvicorn.error.taskhub")

DOMAIN_STATUS: dict[type[DomainException], int] = {
    BadRequestException: status.HTTP_400_BAD_REQUEST,
    AuthenticationException: status.HTTP_401_UNAUTHORIZED,
    ForbiddenException: status.HTTP_403_FORBIDDEN,
    NotFoundException: status.HTTP_404_NOT_FOUND,
    ConflictException: status.HTTP_409_CONFLICT,
    InvalidReferenceException: status.HTTP_422_UNPROCESSABLE_CONTENT,
}
SENSITIVE_FIELDS = ("password", "token")


def is_sensitive(location: object) -> bool:
    return isinstance(location, (list, tuple)) and any(
        isinstance(part, str) and any(word in part for word in SENSITIVE_FIELDS)
        for part in location
    )


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
        description=(
            "TaskHub: JWT access/refresh tokens, workspace RBAC, projects and tasks."
        ),
        lifespan=lifespan,
    )

    app.state.settings = settings

    @app.exception_handler(DomainException)
    async def handle_domain_exception(
        request: Request, exc: DomainException
    ) -> JSONResponse:
        status_code = next(
            (
                code
                for exception_type, code in DOMAIN_STATUS.items()
                if isinstance(exc, exception_type)
            ),
            status.HTTP_400_BAD_REQUEST,
        )
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
            if is_sensitive(error.get("loc", ())):
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
    for router in (users_router, workspaces_router, projects_router, tasks_router):
        app.include_router(router, prefix=API_V1_PREFIX, responses=PROTECTED_ERRORS)
    return app


app = create_app()
