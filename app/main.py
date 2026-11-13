import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.params import PROTECTED_ERRORS
from app.api.v1.auth import router as auth_router
from app.api.v1.comments import router as comments_router
from app.api.v1.labels import router as labels_router
from app.api.v1.projects import router as projects_router
from app.api.v1.tasks import router as tasks_router
from app.api.v1.users import router as users_router
from app.api.v1.workspaces import router as workspaces_router
from app.core.config import Settings, get_settings
from app.core.constants import (
    API_V1_PREFIX,
    APP_NAME,
    APP_VERSION,
    CORS_MAX_AGE_SECONDS,
    PROCESS_TIME_HEADER,
    REQUEST_ID_HEADER,
)
from app.core.errors import register_exception_handlers
from app.core.middleware import RequestContextMiddleware, SecurityHeadersMiddleware
from app.database import Database

logger = logging.getLogger("uvicorn.error.taskhub")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    settings.signing_key()
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
    config = settings or get_settings()
    app = FastAPI(
        title=APP_NAME,
        version=APP_VERSION,
        description=(
            "TaskHub: JWT access/refresh tokens, workspace RBAC, projects, tasks, "
            "labels and comments."
        ),
        lifespan=lifespan,
    )
    app.state.settings = config

    register_exception_handlers(app)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", REQUEST_ID_HEADER],
        expose_headers=[REQUEST_ID_HEADER, PROCESS_TIME_HEADER],
        max_age=CORS_MAX_AGE_SECONDS,
    )
    app.add_middleware(RequestContextMiddleware)

    app.include_router(auth_router, prefix=API_V1_PREFIX)
    for router in (
        users_router,
        workspaces_router,
        projects_router,
        tasks_router,
        labels_router,
        comments_router,
    ):
        app.include_router(router, prefix=API_V1_PREFIX, responses=PROTECTED_ERRORS)
    return app


app = create_app()
