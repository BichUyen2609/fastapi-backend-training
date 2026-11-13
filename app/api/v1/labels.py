from fastapi import APIRouter, Response, status

from app.api.dependencies import LabelServiceDependency
from app.api.params import RESOURCE_ERRORS
from app.models.entities import Label
from app.schemas.base import ResourceId
from app.schemas.label import LabelCreate, LabelResponse, LabelUpdate

router = APIRouter(tags=["Labels"], responses=RESOURCE_ERRORS)


@router.post(
    "/projects/{project_id}/labels",
    response_model=LabelResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_label(
    project_id: ResourceId, data: LabelCreate, service: LabelServiceDependency
) -> Label:
    return await service.create_label(project_id, data)


@router.get("/projects/{project_id}/labels", response_model=list[LabelResponse])
async def list_labels(
    project_id: ResourceId, service: LabelServiceDependency
) -> list[Label]:
    return await service.list_labels(project_id)


@router.patch("/labels/{label_id}", response_model=LabelResponse)
async def update_label(
    label_id: ResourceId, data: LabelUpdate, service: LabelServiceDependency
) -> Label:
    return await service.update_label(label_id, data)


@router.delete(
    "/labels/{label_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_label(
    label_id: ResourceId, service: LabelServiceDependency
) -> Response:
    await service.delete_label(label_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/tasks/{task_id}/labels", response_model=list[LabelResponse])
async def list_task_labels(
    task_id: ResourceId, service: LabelServiceDependency
) -> list[Label]:
    return await service.task_labels(task_id)


@router.post("/tasks/{task_id}/labels/{label_id}", response_model=list[LabelResponse])
async def attach_label(
    task_id: ResourceId, label_id: ResourceId, service: LabelServiceDependency
) -> list[Label]:
    return await service.attach(task_id, label_id)


@router.delete(
    "/tasks/{task_id}/labels/{label_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def detach_label(
    task_id: ResourceId, label_id: ResourceId, service: LabelServiceDependency
) -> Response:
    await service.detach(task_id, label_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
