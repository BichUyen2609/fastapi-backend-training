from sqlalchemy import Select, and_, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import WorkspaceRole
from app.models.entities import Project, Task, User, Workspace, WorkspaceMember
from app.repositories.base import BaseRepository


class TaskRepository(BaseRepository[Task]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Task)

    async def project_exists(self, project_id: int) -> bool:
        return (
            await self.session.scalar(select(exists().where(Project.id == project_id)))
            is True
        )

    async def user_exists(self, user_id: int) -> bool:
        return (
            await self.session.scalar(
                select(exists().where(User.id == user_id, User.is_active.is_(True)))
            )
            is True
        )

    async def project_access(
        self, project_id: int, user_id: int
    ) -> tuple[bool, WorkspaceRole | None]:
        statement = (
            select(Workspace.owner_id, WorkspaceMember.role)
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
            return False, None
        return True, WorkspaceRole.OWNER if row.owner_id == user_id else row.role

    def visible_projects(self, user_id: int) -> Select[tuple[int]]:
        memberships = select(WorkspaceMember.workspace_id).where(
            WorkspaceMember.user_id == user_id
        )
        return (
            select(Project.id)
            .join(Workspace)
            .where(or_(Workspace.owner_id == user_id, Workspace.id.in_(memberships)))
        )
