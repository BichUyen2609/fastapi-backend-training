from typing import NamedTuple

from sqlalchemy import Select, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ProjectStatus, WorkspaceRole
from app.models.entities import Project, Task, Workspace, WorkspaceMember


class WorkspaceAccess(NamedTuple):
    owner_id: int
    role: WorkspaceRole | None


class ProjectAccess(NamedTuple):
    workspace_id: int
    status: ProjectStatus
    role: WorkspaceRole | None


def effective_role(
    owner_id: int, user_id: int, member_role: WorkspaceRole | None
) -> WorkspaceRole | None:
    return WorkspaceRole.OWNER if owner_id == user_id else member_role


class AccessRepository:
    session: AsyncSession

    async def workspace_access(
        self, workspace_id: int, user_id: int
    ) -> WorkspaceAccess | None:
        statement = (
            select(Workspace.owner_id, WorkspaceMember.role)
            .select_from(Workspace)
            .outerjoin(
                WorkspaceMember,
                and_(
                    WorkspaceMember.workspace_id == Workspace.id,
                    WorkspaceMember.user_id == user_id,
                ),
            )
            .where(Workspace.id == workspace_id)
        )
        row = (await self.session.execute(statement)).one_or_none()
        if row is None:
            return None
        return WorkspaceAccess(
            row.owner_id, effective_role(row.owner_id, user_id, row.role)
        )

    async def project_access(
        self, project_id: int, user_id: int
    ) -> ProjectAccess | None:
        statement = (
            select(
                Project.workspace_id,
                Project.status,
                Workspace.owner_id,
                WorkspaceMember.role,
            )
            .select_from(Project)
            .join(Workspace, Project.workspace_id == Workspace.id)
            .outerjoin(
                WorkspaceMember,
                and_(
                    WorkspaceMember.workspace_id == Workspace.id,
                    WorkspaceMember.user_id == user_id,
                ),
            )
            .where(Project.id == project_id)
        )
        row = (await self.session.execute(statement)).one_or_none()
        if row is None:
            return None
        return ProjectAccess(
            row.workspace_id,
            row.status,
            effective_role(row.owner_id, user_id, row.role),
        )

    async def task_project(self, task_id: int) -> int | None:
        result = await self.session.scalars(
            select(Task.project_id).where(Task.id == task_id)
        )
        return result.one_or_none()

    def visible_workspaces(self, user_id: int) -> Select[tuple[int]]:
        memberships = select(WorkspaceMember.workspace_id).where(
            WorkspaceMember.user_id == user_id
        )
        return select(Workspace.id).where(
            or_(Workspace.owner_id == user_id, Workspace.id.in_(memberships))
        )

    def visible_projects(self, user_id: int) -> Select[tuple[int]]:
        return select(Project.id).where(
            Project.workspace_id.in_(self.visible_workspaces(user_id))
        )
