from typing import Any, Generic, TypeVar

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.database import Entity

ModelT = TypeVar("ModelT", bound=Entity)


class BaseRepository(Generic[ModelT]):
    def __init__(self, session: AsyncSession, model: type[ModelT]) -> None:
        self.session = session
        self.model = model

    async def get(self, entity_id: int) -> ModelT | None:
        return await self.session.get(self.model, entity_id)

    async def create(self, values: dict[str, Any]) -> ModelT:
        entity = self.model(**values)
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def update(self, entity_id: int, changes: dict[str, Any]) -> ModelT | None:
        statement = (
            update(self.model)
            .where(self.model.id == entity_id)
            .values(**changes)
            .returning(self.model)
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def delete(self, entity_id: int) -> bool:
        statement = (
            delete(self.model)
            .where(self.model.id == entity_id)
            .returning(self.model.id)
        )
        return (await self.session.execute(statement)).scalar_one_or_none() is not None

    async def paginate(
        self,
        page: int,
        limit: int,
        filters: tuple[ColumnElement[bool], ...] = (),
    ) -> tuple[list[ModelT], int]:
        statement = (
            select(self.model)
            .where(*filters)
            .order_by(self.model.created_at.desc(), self.model.id.desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
        items = list((await self.session.scalars(statement)).all())
        total = await self.session.scalar(
            select(func.count()).select_from(self.model).where(*filters)
        )
        return items, total or 0
