from dataclasses import replace
from datetime import UTC, datetime
from threading import Lock
from typing import Protocol
from uuid import UUID

from app.models.task import Task, TaskChanges


class TaskRepository(Protocol):
    def list_tasks(self) -> list[Task]: ...

    def get_task(self, task_id: UUID) -> Task | None: ...

    def add_task(self, task: Task) -> Task: ...

    def update_task(self, task_id: UUID, changes: TaskChanges) -> Task | None: ...

    def delete_task(self, task_id: UUID) -> bool: ...


class InMemoryTaskRepository:
    """Per-application storage; mutations are atomic across worker threads."""

    def __init__(self) -> None:
        self._tasks: dict[UUID, Task] = {}
        self._lock = Lock()

    def list_tasks(self) -> list[Task]:
        with self._lock:
            return list(self._tasks.values())

    def get_task(self, task_id: UUID) -> Task | None:
        with self._lock:
            return self._tasks.get(task_id)

    def add_task(self, task: Task) -> Task:
        with self._lock:
            self._tasks[task.id] = task
            return task

    def update_task(self, task_id: UUID, changes: TaskChanges) -> Task | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or not changes:
                return task
            updated_task = replace(task, **changes, updated_at=datetime.now(UTC))
            self._tasks[task_id] = updated_task
            return updated_task

    def delete_task(self, task_id: UUID) -> bool:
        with self._lock:
            return self._tasks.pop(task_id, None) is not None
