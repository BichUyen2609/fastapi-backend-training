from typing import Annotated, Any

import pytest
from fastapi import Depends, FastAPI
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.api.dependencies import get_session, get_task_repository
from app.core.config import Settings
from app.core.enums import WorkspaceRole
from app.main import create_app
from app.models.entities import Project, Task, User, Workspace, WorkspaceMember
from app.repositories.base import BaseRepository
from app.repositories.task import TaskRepository

pytestmark = pytest.mark.anyio


async def test_repository_override_is_used_for_every_crud_operation(
    application: FastAPI, client: AsyncClient, references: dict[str, int]
) -> None:
    calls: list[str] = []

    class TrackingRepository(TaskRepository):
        async def create(self, values: dict[str, Any]) -> Task:
            calls.append("create")
            return await super().create(values)

        async def get(self, entity_id: int) -> Task | None:
            calls.append("get")
            return await super().get(entity_id)

        async def update(self, entity_id: int, changes: dict[str, Any]) -> Task | None:
            calls.append("update")
            return await super().update(entity_id, changes)

        async def delete(self, entity_id: int) -> bool:
            calls.append("delete")
            return await super().delete(entity_id)

        async def paginate(
            self,
            page: int,
            limit: int,
            filters: tuple[ColumnElement[bool], ...] = (),
        ) -> tuple[list[Task], int]:
            calls.append("list")
            return await super().paginate(page, limit, filters)

    def override_repository(
        session: Annotated[AsyncSession, Depends(get_session)],
    ) -> TaskRepository:
        return TrackingRepository(session)

    application.dependency_overrides[get_task_repository] = override_repository
    response = await client.post(
        "/api/v1/tasks", json=references | {"title": "Injected"}
    )
    assert response.status_code == 201
    task_url = f"/api/v1/tasks/{response.json()['id']}"
    assert (
        await client.get(
            "/api/v1/tasks", params={"project_id": references["project_id"]}
        )
    ).status_code == 200
    assert (await client.get(task_url)).status_code == 200
    assert (await client.patch(task_url, json={"title": "Updated"})).status_code == 200
    assert (await client.delete(task_url)).status_code == 204
    assert calls == ["create", "list", "get", "get", "update", "get", "delete"]


@pytest.mark.parametrize("kind", ["foreign_key", "unique"])
async def test_integrity_error_is_409_and_transaction_rolls_back(
    application: FastAPI, client: AsyncClient, references: dict[str, int], kind: str
) -> None:
    class ConflictingRepository(TaskRepository):
        async def create(self, values: dict[str, Any]) -> Task:
            if kind == "foreign_key":
                return await super().create(values | {"project_id": 2_000_000_000})
            project = await self.session.get(Project, values["project_id"])
            assert project is not None
            self.session.add(
                Project(name=project.name, workspace_id=project.workspace_id)
            )
            await self.session.flush()
            return await super().create(values)

    def override_repository(
        session: Annotated[AsyncSession, Depends(get_session)],
    ) -> TaskRepository:
        return ConflictingRepository(session)

    application.dependency_overrides[get_task_repository] = override_repository
    response = await client.post(
        "/api/v1/tasks", json=references | {"title": "Conflict"}
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "Resource conflicts with existing data"
    application.dependency_overrides.pop(get_task_repository)
    page = (
        await client.get(
            "/api/v1/tasks", params={"project_id": references["project_id"]}
        )
    ).json()
    assert page["total"] == 0
    assert (
        await client.post("/api/v1/tasks", json=references | {"title": "Recovered"})
    ).status_code == 201


async def test_database_persists_between_app_instances(
    application: FastAPI,
    client: AsyncClient,
    references: dict[str, int],
    test_settings: Settings,
) -> None:
    response = await client.post(
        "/api/v1/tasks", json=references | {"title": "Persisted"}
    )
    assert response.status_code == 201
    created = response.json()
    second_app = create_app(test_settings)
    second_app.dependency_overrides[get_session] = application.dependency_overrides[
        get_session
    ]
    async with (
        second_app.router.lifespan_context(second_app),
        AsyncClient(
            transport=ASGITransport(app=second_app),
            base_url="http://second",
            headers={"Authorization": client.headers["Authorization"]},
        ) as second,
    ):
        assert (await second.get(f"/api/v1/tasks/{created['id']}")).json() == created


async def test_partial_updates_preserve_fields_after_stale_reads(
    db_session: AsyncSession,
    references: dict[str, int],
    current_user: User,
) -> None:
    task = await TaskRepository(db_session).create(
        references | {"title": "Original", "created_by": current_user.id}
    )
    connection = await db_session.connection()
    async with (
        AsyncSession(
            bind=connection, join_transaction_mode="create_savepoint"
        ) as first,
        AsyncSession(
            bind=connection, join_transaction_mode="create_savepoint"
        ) as second,
    ):
        first_snapshot = await first.get(Task, task.id)
        second_snapshot = await second.get(Task, task.id)
        assert first_snapshot is not None and second_snapshot is not None
        assert first_snapshot.title == second_snapshot.title == "Original"
        await TaskRepository(first).update(task.id, {"title": "Changed"})
        updated = await TaskRepository(second).update(task.id, {"description": "Added"})
        assert updated is not None
        assert updated.title == "Changed"
        assert updated.description == "Added"


async def test_workspace_and_membership_rollback_together(
    db_session: AsyncSession,
    current_user: User,
) -> None:
    workspace_id = None
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            workspace = await BaseRepository(db_session, Workspace).create(
                {"name": "Atomic", "owner_id": current_user.id}
            )
            workspace_id = workspace.id
            db_session.add(
                WorkspaceMember(
                    workspace_id=workspace.id,
                    user_id=2_000_000_000,
                    role=WorkspaceRole.OWNER,
                )
            )
            await db_session.flush()
    assert workspace_id is not None
    assert (
        await db_session.scalar(
            select(Workspace.id).where(Workspace.id == workspace_id)
        )
        is None
    )
