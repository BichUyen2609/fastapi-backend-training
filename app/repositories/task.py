from sqlalchemy import delete, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Project, Task, TaskLabel, User
from app.repositories.access import AccessRepository
from app.repositories.base import BaseRepository


class TaskRepository(AccessRepository, BaseRepository[Task]):
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

    async def clear_labels(self, task_id: int) -> None:
        await self.session.execute(
            delete(TaskLabel).where(TaskLabel.task_id == task_id)
        )
