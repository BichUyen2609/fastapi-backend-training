from typing import NamedTuple

from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import WorkspaceRole
from app.models.entities import Project, Task, User, Workspace, WorkspaceMember
from app.repositories.access import AccessRepository, effective_role
from app.repositories.base import BaseRepository


class MemberRow(NamedTuple):
    user_id: int
    email: str
    full_name: str
    role: WorkspaceRole


class WorkspaceRepository(AccessRepository, BaseRepository[Workspace]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Workspace)

    async def add_member(
        self, workspace_id: int, user_id: int, role: WorkspaceRole
    ) -> None:
        self.session.add(
            WorkspaceMember(workspace_id=workspace_id, user_id=user_id, role=role)
        )
        await self.session.flush()

    async def set_member_role(
        self, workspace_id: int, user_id: int, role: WorkspaceRole
    ) -> bool:
        statement = (
            update(WorkspaceMember)
            .where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user_id,
            )
            .values(role=role)
            .returning(WorkspaceMember.user_id)
        )
        return (await self.session.execute(statement)).scalar_one_or_none() is not None

    async def remove_member(self, workspace_id: int, user_id: int) -> bool:
        statement = (
            delete(WorkspaceMember)
            .where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user_id,
            )
            .returning(WorkspaceMember.user_id)
        )
        return (await self.session.execute(statement)).scalar_one_or_none() is not None

    async def unassign_tasks(self, workspace_id: int, user_id: int) -> None:
        projects = select(Project.id).where(Project.workspace_id == workspace_id)
        await self.session.execute(
            update(Task)
            .where(Task.assignee_id == user_id, Task.project_id.in_(projects))
            .values(assignee_id=None)
        )

    async def members(
        self, workspace_id: int, owner_id: int, user_id: int | None = None
    ) -> list[MemberRow]:
        statement = (
            select(User.id, User.email, User.full_name, WorkspaceMember.role)
            .select_from(User)
            .outerjoin(
                WorkspaceMember,
                and_(
                    WorkspaceMember.user_id == User.id,
                    WorkspaceMember.workspace_id == workspace_id,
                ),
            )
            .where(
                or_(
                    WorkspaceMember.workspace_id == workspace_id,
                    User.id == owner_id,
                )
            )
            .order_by(User.id)
        )
        if user_id is not None:
            statement = statement.where(User.id == user_id)
        rows = (await self.session.execute(statement)).all()
        return [
            MemberRow(
                row.id,
                row.email,
                row.full_name,
                effective_role(owner_id, row.id, row.role) or WorkspaceRole.VIEWER,
            )
            for row in rows
        ]
