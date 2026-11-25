from sqlalchemy.sql.elements import ColumnElement

from app.core.constants import (
    PROJECT_NAME_TAKEN,
    PROJECT_NOT_FOUND,
)
from app.core.enums import ProjectStatus, WorkspaceRole
from app.core.exceptions import NotFoundException
from app.models.entities import Project, User
from app.repositories.project import ProjectRepository
from app.schemas.project import (
    ProjectCreate,
    ProjectPage,
    ProjectResponse,
    ProjectUpdate,
)
from app.services.base import authorize_project, authorize_workspace, transaction


class ProjectService:
    def __init__(self, repository: ProjectRepository, actor: User) -> None:
        self.repository = repository
        self.actor = actor

    async def create_project(self, workspace_id: int, data: ProjectCreate) -> Project:
        async with transaction(self.repository.session, PROJECT_NAME_TAKEN):
            await authorize_workspace(
                self.repository, self.actor, workspace_id, WorkspaceRole.EDITOR
            )
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
        await authorize_workspace(self.repository, self.actor, workspace_id)
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
        await authorize_project(self.repository, self.actor, project_id)
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
            await authorize_project(
                self.repository, self.actor, project_id, minimum=WorkspaceRole.EDITOR
            )
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
            await authorize_project(
                self.repository, self.actor, project_id, minimum=WorkspaceRole.OWNER
            )
            if not await self.repository.delete(project_id):
                raise NotFoundException(PROJECT_NOT_FOUND)
