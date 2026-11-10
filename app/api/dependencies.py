from collections.abc import AsyncIterator
from typing import Annotated, cast

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Database
from app.repositories.task import TaskRepository
from app.services.task import TaskService


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    database = cast(Database, request.app.state.database)
    async with database.sessions() as session:
        yield session


def get_task_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TaskRepository:
    return TaskRepository(session)


def get_task_service(
    repository: Annotated[TaskRepository, Depends(get_task_repository)],
) -> TaskService:
    return TaskService(repository)


TaskServiceDependency = Annotated[TaskService, Depends(get_task_service)]
