from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.elements import ColumnElement

from app.core.constants import INVALID_ASSIGNEE, PROJECT_NOT_FOUND
from app.core.enums import UserRole, WorkspaceRole
from app.core.exceptions import (
    ConflictException,
    ForbiddenException,
    InvalidReferenceException,
    NotFoundException,
)
from app.models.entities import Task, User
from app.repositories.task import TaskRepository
from app.schemas.task import TaskCreate, TaskPage, TaskResponse, TaskUpdate


class TaskService:
    def __init__(self, repository: TaskRepository, actor: User) -> None:
        self.repository = repository
        self.actor = actor

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        try:
            yield
            await self.repository.session.commit()
        except IntegrityError as exc:
            await self.repository.session.rollback()
            raise ConflictException() from exc
        except BaseException:
            await self.repository.session.rollback()
            raise

    async def authorize_project(
        self, project_id: int, *, write: bool = False, input_reference: bool = False
    ) -> None:
        exists, role = await self.repository.project_access(project_id, self.actor.id)
        if not exists:
            if input_reference:
                raise InvalidReferenceException(PROJECT_NOT_FOUND)
            raise NotFoundException(PROJECT_NOT_FOUND)
        if self.actor.role == UserRole.ADMIN:
            return
        if role is None or (write and role == WorkspaceRole.VIEWER):
            raise ForbiddenException()

    async def validate_assignee(self, project_id: int, assignee_id: int | None) -> None:
        if assignee_id is not None:
            _, role = await self.repository.project_access(project_id, assignee_id)
            if role is None or not await self.repository.user_exists(assignee_id):
                raise InvalidReferenceException(INVALID_ASSIGNEE)

    async def list_tasks(
        self, page: int, limit: int, project_id: int | None = None
    ) -> TaskPage:
        filters: tuple[ColumnElement[bool], ...] = (
            () if project_id is None else (Task.project_id == project_id,)
        )
        if project_id is not None:
            await self.authorize_project(project_id)
        if self.actor.role != UserRole.ADMIN:
            filters += (
                Task.project_id.in_(self.repository.visible_projects(self.actor.id)),
            )
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
                task = await self.repository.update(task_id, changes)
                if task is None:
                    raise NotFoundException()
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
