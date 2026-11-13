from fastapi import APIRouter, Response, status

from app.api.dependencies import ProjectServiceDependency, WorkspaceServiceDependency
from app.api.params import RESOURCE_ERRORS, PageLimit, PageNumber
from app.core.constants import API_V1_PREFIX, DEFAULT_LIMIT, DEFAULT_PAGE
from app.core.enums import ProjectStatus
from app.models.entities import Project, Workspace
from app.schemas.base import ResourceId
from app.schemas.project import ProjectCreate, ProjectPage, ProjectResponse
from app.schemas.workspace import (
    MemberCreate,
    MemberResponse,
    MemberUpdate,
    WorkspaceCreate,
    WorkspacePage,
    WorkspaceResponse,
    WorkspaceUpdate,
)

router = APIRouter(prefix="/workspaces", tags=["Workspaces"], responses=RESOURCE_ERRORS)


@router.post("", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    data: WorkspaceCreate, response: Response, service: WorkspaceServiceDependency
) -> Workspace:
    workspace = await service.create_workspace(data)
    response.headers["Location"] = f"{API_V1_PREFIX}/workspaces/{workspace.id}"
    return workspace


@router.get("", response_model=WorkspacePage)
async def list_workspaces(
    service: WorkspaceServiceDependency,
    page: PageNumber = DEFAULT_PAGE,
    limit: PageLimit = DEFAULT_LIMIT,
) -> WorkspacePage:
    return await service.list_workspaces(page, limit)


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
async def get_workspace(
    workspace_id: ResourceId, service: WorkspaceServiceDependency
) -> Workspace:
    return await service.get_workspace(workspace_id)


@router.patch("/{workspace_id}", response_model=WorkspaceResponse)
async def update_workspace(
    workspace_id: ResourceId,
    data: WorkspaceUpdate,
    service: WorkspaceServiceDependency,
) -> Workspace:
    return await service.update_workspace(workspace_id, data)


@router.delete(
    "/{workspace_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_workspace(
    workspace_id: ResourceId, service: WorkspaceServiceDependency
) -> Response:
    await service.delete_workspace(workspace_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{workspace_id}/members", response_model=list[MemberResponse])
async def list_members(
    workspace_id: ResourceId, service: WorkspaceServiceDependency
) -> list[MemberResponse]:
    return await service.list_members(workspace_id)


@router.post(
    "/{workspace_id}/members",
    response_model=MemberResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_member(
    workspace_id: ResourceId,
    data: MemberCreate,
    service: WorkspaceServiceDependency,
) -> MemberResponse:
    return await service.add_member(workspace_id, data)


@router.patch("/{workspace_id}/members/{user_id}", response_model=MemberResponse)
async def update_member(
    workspace_id: ResourceId,
    user_id: ResourceId,
    data: MemberUpdate,
    service: WorkspaceServiceDependency,
) -> MemberResponse:
    return await service.update_member(workspace_id, user_id, data)


@router.delete(
    "/{workspace_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def remove_member(
    workspace_id: ResourceId,
    user_id: ResourceId,
    service: WorkspaceServiceDependency,
) -> Response:
    await service.remove_member(workspace_id, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{workspace_id}/projects",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_project(
    workspace_id: ResourceId,
    data: ProjectCreate,
    response: Response,
    service: ProjectServiceDependency,
) -> Project:
    project = await service.create_project(workspace_id, data)
    response.headers["Location"] = f"{API_V1_PREFIX}/projects/{project.id}"
    return project


@router.get("/{workspace_id}/projects", response_model=ProjectPage)
async def list_projects(
    workspace_id: ResourceId,
    service: ProjectServiceDependency,
    page: PageNumber = DEFAULT_PAGE,
    limit: PageLimit = DEFAULT_LIMIT,
    status: ProjectStatus | None = None,
) -> ProjectPage:
    return await service.list_projects(workspace_id, page, limit, status)
