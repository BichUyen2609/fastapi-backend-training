from fastapi import APIRouter, Response, status

from app.api.dependencies import ProjectServiceDependency
from app.api.params import RESOURCE_ERRORS
from app.core.enums import ProjectStatus
from app.models.entities import Project
from app.schemas.base import ResourceId
from app.schemas.project import ProjectResponse, ProjectUpdate

router = APIRouter(prefix="/projects", tags=["Projects"], responses=RESOURCE_ERRORS)


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: ResourceId, service: ProjectServiceDependency
) -> Project:
    return await service.get_project(project_id)


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: ResourceId, data: ProjectUpdate, service: ProjectServiceDependency
) -> Project:
    return await service.update_project(project_id, data)


@router.post("/{project_id}/archive", response_model=ProjectResponse)
async def archive_project(
    project_id: ResourceId, service: ProjectServiceDependency
) -> Project:
    return await service.set_status(project_id, ProjectStatus.ARCHIVED)


@router.post("/{project_id}/restore", response_model=ProjectResponse)
async def restore_project(
    project_id: ResourceId, service: ProjectServiceDependency
) -> Project:
    return await service.set_status(project_id, ProjectStatus.ACTIVE)


@router.delete(
    "/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_project(
    project_id: ResourceId, service: ProjectServiceDependency
) -> Response:
    await service.delete_project(project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
