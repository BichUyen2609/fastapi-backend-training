from sqlalchemy.sql.elements import ColumnElement

from app.core.constants import (
    PROJECT_NAME_TAKEN,
    PROJECT_NOT_FOUND,
    WORKSPACE_NOT_FOUND,
)
from app.core.enums import ProjectStatus, WorkspaceRole
from app.core.exceptions import NotFoundException
from app.models.entities import Project, User
from app.repositories.access import ProjectAccess
from app.repositories.project import ProjectRepository
from app.schemas.project import (
    ProjectCreate,
    ProjectPage,
    ProjectResponse,
    ProjectUpdate,
)
from app.services.base import ensure_role, transaction


class ProjectService:
    def __init__(self, repository: ProjectRepository, actor: User) -> None:
        self.repository = repository
        self.actor = actor

    async def authorize_workspace(
        self, workspace_id: int, minimum: WorkspaceRole
    ) -> None:
        access = await self.repository.workspace_access(workspace_id, self.actor.id)
        if access is None:
            raise NotFoundException(WORKSPACE_NOT_FOUND)
        ensure_role(self.actor, access.role, minimum)

    async def authorize(self, project_id: int, minimum: WorkspaceRole) -> ProjectAccess:
        access = await self.repository.project_access(project_id, self.actor.id)
        if access is None:
            raise NotFoundException(PROJECT_NOT_FOUND)
        ensure_role(self.actor, access.role, minimum)
        return access

    async def create_project(self, workspace_id: int, data: ProjectCreate) -> Project:
        async with transaction(self.repository.session, PROJECT_NAME_TAKEN):
            await self.authorize_workspace(workspace_id, WorkspaceRole.EDITOR)
            project = await self.repository.create(
                data.model_dump() | {"workspace_id": workspace_id}
            )
        await self.repository.session.refresh(project)
        return project

    async def list_projects(
        self,
        workspace_id: int,
        page: int,
        limit: int,
        status: ProjectStatus | None = None,
    ) -> ProjectPage:
        await self.authorize_workspace(workspace_id, WorkspaceRole.VIEWER)
        filters: tuple[ColumnElement[bool], ...] = (
            Project.workspace_id == workspace_id,
        )
        if status is not None:
            filters += (Project.status == status,)
        items, total = await self.repository.paginate(page, limit, filters)
        return ProjectPage(
            items=[ProjectResponse.model_validate(item) for item in items],
            total=total,
            page=page,
            limit=limit,
        )

    async def get_project(self, project_id: int) -> Project:
        await self.authorize(project_id, WorkspaceRole.VIEWER)
        project = await self.repository.get(project_id)
        if project is None:
            raise NotFoundException(PROJECT_NOT_FOUND)
        return project

    async def update_project(self, project_id: int, data: ProjectUpdate) -> Project:
        return await self.apply_changes(project_id, data.model_dump(exclude_unset=True))

    async def set_status(self, project_id: int, status: ProjectStatus) -> Project:
        return await self.apply_changes(project_id, {"status": status})

    async def apply_changes(
        self, project_id: int, changes: dict[str, object]
    ) -> Project:
        async with transaction(self.repository.session, PROJECT_NAME_TAKEN):
            await self.authorize(project_id, WorkspaceRole.EDITOR)
            project = (
                await self.repository.update(project_id, changes)
                if changes
                else await self.repository.get(project_id)
            )
            if project is None:
                raise NotFoundException(PROJECT_NOT_FOUND)
        return project

    async def delete_project(self, project_id: int) -> None:
        async with transaction(self.repository.session):
            await self.authorize(project_id, WorkspaceRole.OWNER)
            if not await self.repository.delete(project_id):
                raise NotFoundException(PROJECT_NOT_FOUND)
