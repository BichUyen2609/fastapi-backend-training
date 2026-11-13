from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Label, TaskLabel
from app.repositories.access import AccessRepository
from app.repositories.base import BaseRepository


class LabelRepository(AccessRepository, BaseRepository[Label]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Label)

    async def for_project(self, project_id: int) -> list[Label]:
        result = await self.session.scalars(
            select(Label)
            .where(Label.project_id == project_id)
            .order_by(Label.name, Label.id)
        )
        return list(result.all())

    async def for_task(self, task_id: int) -> list[Label]:
        result = await self.session.scalars(
            select(Label)
            .join(TaskLabel, TaskLabel.label_id == Label.id)
            .where(TaskLabel.task_id == task_id)
            .order_by(Label.name, Label.id)
        )
        return list(result.all())

    async def attach(self, task_id: int, label_id: int) -> None:
        await self.session.execute(
            insert(TaskLabel)
            .values(task_id=task_id, label_id=label_id)
            .on_conflict_do_nothing()
        )

    async def detach(self, task_id: int, label_id: int) -> None:
        await self.session.execute(
            delete(TaskLabel).where(
                TaskLabel.task_id == task_id, TaskLabel.label_id == label_id
            )
        )
