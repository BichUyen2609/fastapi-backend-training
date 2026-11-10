import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.api.v1.tasks import router as tasks_router
from app.core.constants import API_V1_PREFIX, APP_NAME, APP_VERSION
from app.core.exceptions import NotFoundException
from app.repositories.task import InMemoryTaskRepository

logger = logging.getLogger("uvicorn.error.taskhub")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.task_repository = InMemoryTaskRepository()
    logger.info("Starting %s", APP_NAME)
    try:
        yield
    finally:
        del app.state.task_repository
        logger.info("Stopping %s", APP_NAME)


def create_app() -> FastAPI:
    app = FastAPI(
        title=APP_NAME,
        version=APP_VERSION,
        description="Day 1: core setup, layered architecture, and Task CRUD.",
        lifespan=lifespan,
    )

    @app.exception_handler(NotFoundException)
    async def handle_not_found(
        request: Request, exc: NotFoundException
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": exc.message},
        )

    app.include_router(tasks_router, prefix=API_V1_PREFIX)
    return app


app = create_app()
