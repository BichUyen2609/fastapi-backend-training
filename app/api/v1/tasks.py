from uuid import UUID

from fastapi import APIRouter, Response, status

from app.api.dependencies import TaskServiceDependency
from app.core.constants import API_V1_PREFIX, TASK_NOT_FOUND
from app.models.task import Task
from app.schemas.base import ErrorResponse
from app.schemas.task import TaskCreate, TaskResponse, TaskUpdate

router = APIRouter(prefix="/tasks", tags=["Tasks"])

not_found_response: dict[int | str, dict[str, object]] = {
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorResponse,
        "description": TASK_NOT_FOUND,
    }
}


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
def create_task(
    data: TaskCreate, response: Response, service: TaskServiceDependency
) -> Task:
    task = service.create_task(data)
    response.headers["Location"] = f"{API_V1_PREFIX}/tasks/{task.id}"
    return task


@router.get("", response_model=list[TaskResponse])
def list_tasks(service: TaskServiceDependency) -> list[Task]:
    return service.list_tasks()


@router.get("/{task_id}", response_model=TaskResponse, responses=not_found_response)
def get_task(task_id: UUID, service: TaskServiceDependency) -> Task:
    return service.get_task(task_id)


@router.patch("/{task_id}", response_model=TaskResponse, responses=not_found_response)
def update_task(
    task_id: UUID, data: TaskUpdate, service: TaskServiceDependency
) -> Task:
    return service.update_task(task_id, data)


@router.delete(
    "/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=not_found_response,
)
def delete_task(task_id: UUID, service: TaskServiceDependency) -> Response:
    service.delete_task(task_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
