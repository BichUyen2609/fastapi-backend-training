from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

from app.core.exceptions import NotFoundException
from app.models.task import Task, TaskChanges
from app.repositories.task import TaskRepository
from app.schemas.task import TaskCreate, TaskUpdate


class TaskService:
    def __init__(self, repository: TaskRepository) -> None:
        self.repository = repository

    def list_tasks(self) -> list[Task]:
        return self.repository.list_tasks()

    def get_task(self, task_id: UUID) -> Task:
        task = self.repository.get_task(task_id)
        if task is None:
            raise NotFoundException()
        return task

    def create_task(self, data: TaskCreate) -> Task:
        now = datetime.now(UTC)
        task = Task(
            id=uuid4(),
            title=data.title,
            description=data.description,
            status=data.status,
            priority=data.priority,
            due_date=data.due_date,
            created_at=now,
            updated_at=now,
        )
        return self.repository.add_task(task)

    def update_task(self, task_id: UUID, data: TaskUpdate) -> Task:
        # Pydantic has validated supplied values; explicit nullable fields survive.
        changes = cast(TaskChanges, data.model_dump(exclude_unset=True))
        task = self.repository.update_task(task_id, changes)
        if task is None:
            raise NotFoundException()
        return task

    def delete_task(self, task_id: UUID) -> None:
        if not self.repository.delete_task(task_id):
            raise NotFoundException()
