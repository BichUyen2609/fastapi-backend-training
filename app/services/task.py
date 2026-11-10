from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.exc import IntegrityError

from app.core.constants import PROJECT_NOT_FOUND, USER_NOT_FOUND
from app.core.exceptions import (
    ConflictException,
    InvalidReferenceException,
    NotFoundException,
)
from app.models.entities import Task
from app.repositories.task import TaskRepository
from app.schemas.task import TaskCreate, TaskPage, TaskResponse, TaskUpdate


class TaskService:
    def __init__(self, repository: TaskRepository) -> None:
        self.repository = repository

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        try:
            async with self.repository.session.begin():
                yield
        except IntegrityError as exc:
            raise ConflictException() from exc

    async def validate_references(
        self,
        project_id: int | None = None,
        created_by: int | None = None,
        assignee_id: int | None = None,
    ) -> None:
        if project_id is not None and not await self.repository.project_exists(
            project_id
        ):
            raise InvalidReferenceException(PROJECT_NOT_FOUND)
        for user_id in (created_by, assignee_id):
            if user_id is not None and not await self.repository.user_exists(user_id):
                raise InvalidReferenceException(USER_NOT_FOUND)

    async def list_tasks(
        self, page: int, limit: int, project_id: int | None = None
    ) -> TaskPage:
        if project_id is not None and not await self.repository.project_exists(
            project_id
        ):
            raise NotFoundException(PROJECT_NOT_FOUND)
        filters = () if project_id is None else (Task.project_id == project_id,)
        tasks, total = await self.repository.paginate(page, limit, filters)
        return TaskPage(
            items=[TaskResponse.model_validate(task) for task in tasks],
            total=total,
            page=page,
            limit=limit,
        )

    async def get_task(self, task_id: int) -> Task:
        task = await self.repository.get(task_id)
        if task is None:
            raise NotFoundException()
        return task

    async def create_task(self, data: TaskCreate) -> Task:
        async with self.transaction():
            await self.validate_references(
                data.project_id, data.created_by, data.assignee_id
            )
            task = await self.repository.create(data.model_dump())
        await self.repository.session.refresh(task)
        return task

    async def update_task(self, task_id: int, data: TaskUpdate) -> Task:
        changes = data.model_dump(exclude_unset=True)
        async with self.transaction():
            await self.validate_references(
                project_id=data.project_id, assignee_id=data.assignee_id
            )
            task = (
                await self.repository.update(task_id, changes)
                if changes
                else await self.repository.get(task_id)
            )
            if task is None:
                raise NotFoundException()
        await self.repository.session.refresh(task)
        return task

    async def delete_task(self, task_id: int) -> None:
        async with self.transaction():
            if not await self.repository.delete(task_id):
                raise NotFoundException()
