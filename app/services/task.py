from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.sql.elements import ColumnElement

from app.core.constants import INVALID_ASSIGNEE
from app.core.enums import UserRole
from app.core.exceptions import InvalidReferenceException, NotFoundException
from app.models.entities import Task, User
from app.repositories.task import TaskRepository
from app.schemas.task import (
    TaskCreate,
    TaskFilters,
    TaskPage,
    TaskResponse,
    TaskUpdate,
)
from app.services.base import authorize_project, transaction


class TaskService:
    def __init__(self, repository: TaskRepository, actor: User) -> None:
        self.repository = repository
        self.actor = actor

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        async with transaction(self.repository.session):
            yield

    async def authorize_project(
        self, project_id: int, *, write: bool = False, input_reference: bool = False
    ) -> None:
        await authorize_project(
            self.repository,
            self.actor,
            project_id,
            write=write,
            input_reference=input_reference,
        )

    async def validate_assignee(self, project_id: int, assignee_id: int | None) -> None:
        if assignee_id is not None:
            access = await self.repository.project_access(project_id, assignee_id)
            if (
                access is None
                or access.role is None
                or not await self.repository.user_exists(assignee_id)
            ):
                raise InvalidReferenceException(INVALID_ASSIGNEE)

    async def list_tasks(
        self,
        page: int,
        limit: int,
        project_id: int | None = None,
        filters: TaskFilters | None = None,
    ) -> TaskPage:
        criteria = filters or TaskFilters()
        conditions: tuple[ColumnElement[bool], ...] = tuple(
            condition
            for value, condition in (
                (project_id, Task.project_id == project_id),
                (criteria.status, Task.status == criteria.status),
                (criteria.priority, Task.priority == criteria.priority),
                (criteria.assignee_id, Task.assignee_id == criteria.assignee_id),
            )
            if value is not None
        )
        if project_id is not None:
            await self.authorize_project(project_id)
        if self.actor.role != UserRole.ADMIN:
            conditions += (
                Task.project_id.in_(self.repository.visible_projects(self.actor.id)),
            )
        tasks, total = await self.repository.paginate(page, limit, conditions)
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
        await self.authorize_project(task.project_id)
        return task

    async def create_task(self, data: TaskCreate) -> Task:
        async with self.transaction():
            await self.authorize_project(
                data.project_id, write=True, input_reference=True
            )
            await self.validate_assignee(data.project_id, data.assignee_id)
            task = await self.repository.create(
                data.model_dump() | {"created_by": self.actor.id}
            )
        await self.repository.session.refresh(task)
        return task

    async def update_task(self, task_id: int, data: TaskUpdate) -> Task:
        changes = data.model_dump(exclude_unset=True)
        async with self.transaction():
            task = await self.repository.get(task_id)
            if task is None:
                raise NotFoundException()
            await self.authorize_project(task.project_id, write=True)
            target_project = (
                data.project_id if data.project_id is not None else task.project_id
            )
            if "project_id" in changes:
                await self.authorize_project(
                    target_project, write=True, input_reference=True
                )
            assignee_id = (
                data.assignee_id if "assignee_id" in changes else task.assignee_id
            )
            if "assignee_id" in changes or "project_id" in changes:
                await self.validate_assignee(target_project, assignee_id)
            if changes:
                moved = target_project != task.project_id
                task = await self.repository.update(task_id, changes)
                if task is None:
                    raise NotFoundException()
                if moved:
                    await self.repository.clear_labels(task_id)
        await self.repository.session.refresh(task)
        return task

    async def delete_task(self, task_id: int) -> None:
        async with self.transaction():
            task = await self.repository.get(task_id)
            if task is None:
                raise NotFoundException()
            await self.authorize_project(task.project_id, write=True)
            if not await self.repository.delete(task_id):
                raise NotFoundException()
