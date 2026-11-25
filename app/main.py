import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.params import PROTECTED_ERRORS, error_responses
from app.api.v1.auth import router as auth_router
from app.api.v1.comments import router as comments_router
from app.api.v1.labels import router as labels_router
from app.api.v1.projects import router as projects_router
from app.api.v1.tasks import router as tasks_router
from app.api.v1.users import router as users_router
from app.api.v1.workspaces import router as workspaces_router
from app.core.cache import TaskCache
from app.core.config import Settings, get_settings
from app.core.constants import (
    API_V1_PREFIX,
    APP_NAME,
    APP_VERSION,
    CORS_MAX_AGE_SECONDS,
    PROCESS_TIME_HEADER,
    REQUEST_ID_HEADER,
    SERVICE_UNAVAILABLE,
)
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware, SecurityHeadersMiddleware
from app.database import Database

logger = logging.getLogger("taskhub.lifecycle")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    settings.signing_key()
    configure_logging(settings)
    database = Database(settings)
    cache = TaskCache(settings)
    try:
        async with database.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        app.state.database = database
        app.state.task_cache = cache
        logger.info("Starting %s", APP_NAME)
        yield
    finally:
        try:
            await cache.close()
        finally:
            await database.close()
        logger.info("Stopping %s", APP_NAME)


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or get_settings()
    app = FastAPI(
        title=APP_NAME,
        version=APP_VERSION,
        docs_url="/docs" if config.docs_enabled else None,
        redoc_url="/redoc" if config.docs_enabled else None,
        openapi_url="/openapi.json" if config.docs_enabled else None,
        openapi_tags=[
            {
                "name": "Authentication",
                "description": "Register, login, rotate refresh tokens and logout.",
            },
            {
                "name": "Users",
                "description": "Current profile and password management.",
            },
            {
                "name": "Workspaces",
                "description": "Workspace ownership and role-based memberships.",
            },
            {
                "name": "Projects",
                "description": "Workspace projects, archive and restore.",
            },
            {
                "name": "Tasks",
                "description": "Task CRUD, assignments, filters and Redis caching.",
            },
            {
                "name": "Labels",
                "description": "Project labels and task-label associations.",
            },
            {
                "name": "Comments",
                "description": "Task comments and author/owner permissions.",
            },
            {"name": "Health", "description": "Public liveness and readiness probes."},
        ],
        responses=error_responses(422, 500, 503),
        swagger_ui_parameters={
            "persistAuthorization": False,
            "displayRequestDuration": True,
        },
        description=(
            "TaskHub: JWT access/refresh tokens, workspace RBAC, projects, tasks, "
            "labels and comments. Use Authorize with email as username. "
            "Bearer tokens are required for all business resources. "
            "Errors include detail, code and request_id. PATCH omits unchanged fields; "
            "only nullable fields accept null. Assignments schedule email after commit."
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

    @app.get("/health/live", tags=["Health"], summary="Check process liveness")
    async def liveness() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", tags=["Health"], summary="Check database readiness")
    async def readiness(request: Request) -> dict[str, str]:
        database: Database = request.app.state.database
        try:
            async with database.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except (SQLAlchemyError, OSError) as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=SERVICE_UNAVAILABLE,
                headers={"Retry-After": "5"},
            ) from exc
        cache: TaskCache = request.app.state.task_cache
        cache_status = "disabled"
        if cache.client is not None:
            try:
                await cache.client.ping()
                cache_status = "up"
            except RedisError:
                cache_status = "unavailable"
        return {"status": "ready", "database": "up", "cache": cache_status}

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
