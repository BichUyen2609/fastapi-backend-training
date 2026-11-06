from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import cast
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import get_task_repository
from app.main import create_app
from app.models.task import Task, TaskChanges
from app.repositories.task import InMemoryTaskRepository, TaskRepository
from app.schemas.task import TaskCreate
from app.services.task import TaskService


class FakeTaskRepository:
    """An independent repository implementation for the DI regression test."""

    def __init__(self) -> None:
        self.tasks: dict[UUID, Task] = {}
        self.calls: list[str] = []

    def list_tasks(self) -> list[Task]:
        self.calls.append("list")
        return list(self.tasks.values())

    def get_task(self, task_id: UUID) -> Task | None:
        self.calls.append("get")
        return self.tasks.get(task_id)

    def add_task(self, task: Task) -> Task:
        self.calls.append("add")
        self.tasks[task.id] = task
        return task

    def update_task(self, task_id: UUID, changes: TaskChanges) -> Task | None:
        self.calls.append("update")
        task = self.tasks.get(task_id)
        if task is None:
            return None
        updated = replace(task, **changes)
        self.tasks[task_id] = updated
        return updated

    def delete_task(self, task_id: UUID) -> bool:
        self.calls.append("delete")
        return self.tasks.pop(task_id, None) is not None


def test_repository_override_is_used_for_every_crud_operation(
    application: FastAPI,
) -> None:
    repository = FakeTaskRepository()

    def override_repository() -> TaskRepository:
        return repository

    application.dependency_overrides[get_task_repository] = override_repository
    with TestClient(application) as client:
        response = client.post("/api/v1/tasks", json={"title": "Injected"})
        assert response.status_code == 201
        task_id = UUID(response.json()["id"])
        task_url = f"/api/v1/tasks/{task_id}"
        assert isinstance(repository.tasks[task_id], Task)
        assert client.get("/api/v1/tasks").json()[0]["title"] == "Injected"
        assert client.get(task_url).status_code == 200
        response = client.patch(task_url, json={"title": "Updated"})
        assert response.status_code == 200
        assert repository.tasks[task_id].title == "Updated"
        assert client.delete(task_url).status_code == 204
        assert repository.tasks == {}
        assert repository.calls == ["add", "list", "get", "update", "delete"]
        original_repository = cast(
            InMemoryTaskRepository, application.state.task_repository
        )
        assert original_repository.list_tasks() == []


def test_application_instances_have_independent_storage() -> None:
    with TestClient(create_app()) as first, TestClient(create_app()) as second:
        assert (
            first.post("/api/v1/tasks", json={"title": "First app"}).status_code == 201
        )
        assert second.get("/api/v1/tasks").json() == []


def test_concurrent_partial_updates_preserve_both_fields() -> None:
    repository = InMemoryTaskRepository()
    task = TaskService(repository).create_task(TaskCreate(title="Original"))

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(repository.update_task, task.id, {"title": "Changed"})
        second = executor.submit(
            repository.update_task, task.id, {"description": "Added description"}
        )
        assert first.result() is not None
        assert second.result() is not None

    updated = repository.get_task(task.id)
    assert updated is not None
    assert updated.title == "Changed"
    assert updated.description == "Added description"
    assert task.title == "Original"
    assert task.description is None
