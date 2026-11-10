import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.v1.tasks import router as tasks_router
from app.core.config import Settings, get_settings
from app.core.constants import API_V1_PREFIX, APP_NAME, APP_VERSION
from app.core.exceptions import (
    ConflictException,
    DomainException,
    InvalidReferenceException,
    NotFoundException,
)
from app.database import Database

logger = logging.getLogger("uvicorn.error.taskhub")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    database = Database(app.state.settings or get_settings())
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
        description="TaskHub: async PostgreSQL persistence and paginated Task CRUD.",
        lifespan=lifespan,
    )

    app.state.settings = settings

    @app.exception_handler(NotFoundException)
    @app.exception_handler(ConflictException)
    @app.exception_handler(InvalidReferenceException)
    async def handle_domain_exception(
        request: Request, exc: DomainException
    ) -> JSONResponse:
        status_code = status.HTTP_404_NOT_FOUND
        if isinstance(exc, ConflictException):
            status_code = status.HTTP_409_CONFLICT
        elif isinstance(exc, InvalidReferenceException):
            status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
        return JSONResponse(
            status_code=status_code,
            content={"detail": exc.message},
        )

    app.include_router(tasks_router, prefix=API_V1_PREFIX)
    return app


app = create_app()
