from typing import Annotated, cast

from fastapi import Depends, Request

from app.repositories.task import TaskRepository
from app.services.task import TaskService


def get_task_repository(request: Request) -> TaskRepository:
    return cast(TaskRepository, request.app.state.task_repository)


def get_task_service(
    repository: Annotated[TaskRepository, Depends(get_task_repository)],
) -> TaskService:
    return TaskService(repository)


TaskServiceDependency = Annotated[TaskService, Depends(get_task_service)]
