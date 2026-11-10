from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.dependencies import TaskServiceDependency
from app.core.constants import (
    API_V1_PREFIX,
    DEFAULT_LIMIT,
    DEFAULT_PAGE,
    MAX_ENTITY_ID,
    MAX_LIMIT,
)
from app.models.entities import Task
from app.schemas.base import ErrorResponse, ResourceId
from app.schemas.task import TaskCreate, TaskPage, TaskResponse, TaskUpdate

router = APIRouter(tags=["Tasks"])
PageNumber = Annotated[int, Query(ge=1, le=MAX_ENTITY_ID)]
PageLimit = Annotated[int, Query(ge=1, le=MAX_LIMIT)]
error_responses: dict[int | str, dict[str, object]] = {
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorResponse,
        "description": "Resource not found",
    },
    status.HTTP_409_CONFLICT: {"model": ErrorResponse, "description": "Data conflict"},
    status.HTTP_422_UNPROCESSABLE_CONTENT: {
        "model": ErrorResponse,
        "description": "Invalid input or reference",
    },
}


@router.post(
    "/tasks",
    response_model=TaskResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        code: error_responses[code]
        for code in (status.HTTP_409_CONFLICT, status.HTTP_422_UNPROCESSABLE_CONTENT)
    },
)
async def create_task(
    data: TaskCreate, response: Response, service: TaskServiceDependency
) -> Task:
    task = await service.create_task(data)
    response.headers["Location"] = f"{API_V1_PREFIX}/tasks/{task.id}"
    return task


@router.get("/tasks", response_model=TaskPage, responses=error_responses)
async def list_tasks(
    service: TaskServiceDependency,
    page: PageNumber = DEFAULT_PAGE,
    limit: PageLimit = DEFAULT_LIMIT,
    project_id: ResourceId | None = None,
) -> TaskPage:
    return await service.list_tasks(page, limit, project_id)


@router.get(
    "/projects/{project_id}/tasks", response_model=TaskPage, responses=error_responses
)
async def list_project_tasks(
    project_id: ResourceId,
    service: TaskServiceDependency,
    page: PageNumber = DEFAULT_PAGE,
    limit: PageLimit = DEFAULT_LIMIT,
) -> TaskPage:
    return await service.list_tasks(page, limit, project_id)


@router.get("/tasks/{task_id}", response_model=TaskResponse, responses=error_responses)
async def get_task(task_id: ResourceId, service: TaskServiceDependency) -> Task:
    return await service.get_task(task_id)


@router.patch(
    "/tasks/{task_id}", response_model=TaskResponse, responses=error_responses
)
async def update_task(
    task_id: ResourceId, data: TaskUpdate, service: TaskServiceDependency
) -> Task:
    return await service.update_task(task_id, data)


@router.delete(
    "/tasks/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=error_responses,
)
async def delete_task(task_id: ResourceId, service: TaskServiceDependency) -> Response:
    await service.delete_task(task_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
