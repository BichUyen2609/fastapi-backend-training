from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.dependencies import TaskServiceDependency
from app.api.params import RESOURCE_ERRORS, PageLimit, PageNumber, error_responses
from app.core.constants import API_V1_PREFIX, DEFAULT_LIMIT, DEFAULT_PAGE
from app.models.entities import Task
from app.schemas.base import ResourceId
from app.schemas.task import (
    TaskCreate,
    TaskFilters,
    TaskPage,
    TaskResponse,
    TaskUpdate,
)

router = APIRouter(tags=["Tasks"])
FilterQuery = Annotated[TaskFilters, Query()]


@router.post(
    "/tasks",
    response_model=TaskResponse,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(
        status.HTTP_409_CONFLICT, status.HTTP_422_UNPROCESSABLE_CONTENT
    ),
)
async def create_task(
    data: TaskCreate, response: Response, service: TaskServiceDependency
) -> Task:
    task = await service.create_task(data)
    response.headers["Location"] = f"{API_V1_PREFIX}/tasks/{task.id}"
    return task


@router.get("/tasks", response_model=TaskPage, responses=RESOURCE_ERRORS)
async def list_tasks(
    response: Response,
    service: TaskServiceDependency,
    filters: FilterQuery,
    page: PageNumber = DEFAULT_PAGE,
    limit: PageLimit = DEFAULT_LIMIT,
    project_id: ResourceId | None = None,
) -> TaskPage:
    response.headers["Cache-Control"] = "private, no-store"
    return await service.list_tasks(page, limit, project_id, filters)


@router.get(
    "/projects/{project_id}/tasks", response_model=TaskPage, responses=RESOURCE_ERRORS
)
async def list_project_tasks(
    project_id: ResourceId,
    response: Response,
    service: TaskServiceDependency,
    filters: FilterQuery,
    page: PageNumber = DEFAULT_PAGE,
    limit: PageLimit = DEFAULT_LIMIT,
) -> TaskPage:
    response.headers["Cache-Control"] = "private, no-store"
    return await service.list_tasks(page, limit, project_id, filters)


@router.get("/tasks/{task_id}", response_model=TaskResponse, responses=RESOURCE_ERRORS)
async def get_task(task_id: ResourceId, service: TaskServiceDependency) -> Task:
    return await service.get_task(task_id)


@router.patch(
    "/tasks/{task_id}", response_model=TaskResponse, responses=RESOURCE_ERRORS
)
async def update_task(
    task_id: ResourceId, data: TaskUpdate, service: TaskServiceDependency
) -> Task:
    return await service.update_task(task_id, data)


@router.delete(
    "/tasks/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=RESOURCE_ERRORS,
)
async def delete_task(task_id: ResourceId, service: TaskServiceDependency) -> Response:
    await service.delete_task(task_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
