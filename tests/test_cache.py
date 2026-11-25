import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.parse import urlsplit
from uuid import uuid4

import anyio
import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx2 import AsyncClient
from pydantic import ValidationError
from redis.exceptions import ConnectionError, RedisError
from sqlalchemy import Connection, delete, select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.schema import CreateSchema, DropSchema

from app.api.dependencies import get_task_cache
from app.core.cache import TaskCache
from app.core.config import Settings, get_settings
from app.core.enums import WorkspaceRole
from app.core.security import hash_password
from app.models.entities import Project, Task, User, Workspace, WorkspaceMember
from app.repositories.task import TaskRepository
from app.schemas.task import TaskFilters, TaskPage
from tests.test_auth import bearer, new_user
from tests.test_workspaces import join

pytestmark = pytest.mark.anyio


@pytest.fixture
async def cache(test_settings: Settings) -> AsyncIterator[TaskCache]:
    test_url = test_settings.test_redis_url
    assert test_url is not None, "Set TEST_REDIS_URL to a separate Redis database"
    assert int(urlsplit(str(test_url)).path.lstrip("/") or "0") > 0
    assert str(test_url) != str(get_settings().redis_url)
    settings = Settings.model_validate(
        test_settings.model_dump() | {"redis_url": test_url}
    )
    cache = TaskCache(settings)
    assert cache.client is not None
    await cache.client.ping()
    try:
        yield cache
    finally:
        keys = [key async for key in cache.client.scan_iter(f"{cache.namespace}:*")]
        if keys:
            await cache.client.delete(*keys)
        await cache.close()


@pytest.fixture
async def cached_client(
    client: AsyncClient, application: FastAPI, cache: TaskCache
) -> AsyncIterator[AsyncClient]:
    application.dependency_overrides[get_task_cache] = lambda: cache
    try:
        yield client
    finally:
        application.dependency_overrides.pop(get_task_cache)


async def test_cache_hit_skips_task_queries_and_is_shared_between_routes(
    cached_client: AsyncClient,
    project: Project,
    cache: TaskCache,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = await cached_client.post(
        "/api/v1/tasks", json={"project_id": project.id, "title": "Cached"}
    )
    assert response.status_code == 201
    url = f"/api/v1/projects/{project.id}/tasks"
    first = await cached_client.get(url)
    assert first.status_code == 200
    assert first.json()["items"][0] == response.json()
    assert first.headers["cache-control"] == "private, no-store"
    paginate = AsyncMock(side_effect=AssertionError("Cache hit must skip task queries"))
    monkeypatch.setattr(TaskRepository, "paginate", paginate)
    assert (await cached_client.get(url)).json() == first.json()
    alias = await cached_client.get("/api/v1/tasks", params={"project_id": project.id})
    assert alias.json() == first.json()
    paginate.assert_not_awaited()
    assert cache.client is not None
    keys = [key async for key in cache.client.scan_iter(f"{cache.namespace}:*")]
    assert len(keys) == 1
    assert 0 < await cache.client.ttl(keys[0]) <= cache.ttl


async def test_filters_pagination_and_projects_have_independent_cache_entries(
    cached_client: AsyncClient, project: Project, current_user: User
) -> None:
    for title, status, priority, assignee in [
        ("First", "TODO", "LOW", None),
        ("Second", "DONE", "HIGH", current_user.id),
    ]:
        response = await cached_client.post(
            "/api/v1/tasks",
            json={
                "project_id": project.id,
                "title": title,
                "status": status,
                "priority": priority,
                "assignee_id": assignee,
            },
        )
        assert response.status_code == 201
    url = f"/api/v1/projects/{project.id}/tasks"
    queries: list[dict[str, str | int]] = [
        {},
        {"status": "TODO"},
        {"status": "DONE"},
        {"priority": "HIGH"},
        {"assignee_id": current_user.id},
        {"limit": 1, "page": 1},
        {"limit": 1, "page": 2},
        {"status": "TODO", "priority": "HIGH"},
    ]
    expected = [
        ["Second", "First"],
        ["First"],
        ["Second"],
        ["Second"],
        ["Second"],
        ["Second"],
        ["First"],
        [],
    ]
    for _ in range(2):
        for query, titles in zip(queries, expected, strict=True):
            response = await cached_client.get(url, params=query)
            assert response.status_code == 200
            assert [item["title"] for item in response.json()["items"]] == titles
            if query.get("limit") == 1:
                assert response.json()["total"] == 2
    created = await cached_client.post(
        f"/api/v1/workspaces/{project.workspace_id}/projects", json={"name": "Other"}
    )
    assert created.status_code == 201
    empty = await cached_client.get(f"/api/v1/projects/{created.json()['id']}/tasks")
    assert empty.json()["total"] == 0


async def test_create_update_and_delete_invalidate_every_query_variant(
    cached_client: AsyncClient, project: Project
) -> None:
    url = f"/api/v1/projects/{project.id}/tasks"
    assert (await cached_client.get(url)).json()["total"] == 0
    assert (await cached_client.get(url, params={"status": "DONE"})).json()[
        "total"
    ] == 0
    created = await cached_client.post(
        "/api/v1/tasks", json={"project_id": project.id, "title": "Before"}
    )
    task_url = f"/api/v1/tasks/{created.json()['id']}"
    assert (await cached_client.get(url)).json()["total"] == 1
    changed = await cached_client.patch(
        task_url, json={"title": "After", "status": "DONE", "description": "New"}
    )
    assert changed.status_code == 200
    for query in ({}, {"status": "DONE"}):
        result = await cached_client.get(url, params=query)
        assert result.json()["items"] == [changed.json()]
    assert (await cached_client.delete(task_url)).status_code == 204
    for query in ({}, {"status": "DONE"}):
        assert (await cached_client.get(url, params=query)).json()["total"] == 0


async def test_move_invalidates_both_source_and_target_projects(
    cached_client: AsyncClient, project: Project
) -> None:
    other = await cached_client.post(
        f"/api/v1/workspaces/{project.workspace_id}/projects", json={"name": "Target"}
    )
    target_id = other.json()["id"]
    created = await cached_client.post(
        "/api/v1/tasks", json={"project_id": project.id, "title": "Move"}
    )
    source = f"/api/v1/projects/{project.id}/tasks"
    target = f"/api/v1/projects/{target_id}/tasks"
    assert (await cached_client.get(source)).json()["total"] == 1
    assert (await cached_client.get(target)).json()["total"] == 0
    response = await cached_client.patch(
        f"/api/v1/tasks/{created.json()['id']}", json={"project_id": target_id}
    )
    assert response.status_code == 200
    assert (await cached_client.get(source)).json()["total"] == 0
    assert (await cached_client.get(target)).json()["items"] == [response.json()]


async def test_warm_cache_still_checks_authentication_and_current_membership(
    cached_client: AsyncClient,
    db_session: AsyncSession,
    project: Project,
    test_settings: Settings,
) -> None:
    url = f"/api/v1/projects/{project.id}/tasks"
    assert (await cached_client.get(url)).status_code == 200
    outsider = await new_user(db_session)
    denied = await cached_client.get(url, headers=bearer(outsider.id, test_settings))
    assert denied.status_code == 403
    viewer = await join(db_session, project.workspace_id, WorkspaceRole.VIEWER)
    headers = bearer(viewer.id, test_settings)
    assert (await cached_client.get(url, headers=headers)).status_code == 200
    removed = await cached_client.delete(
        f"/api/v1/workspaces/{project.workspace_id}/members/{viewer.id}"
    )
    assert removed.status_code == 204
    assert (await cached_client.get(url, headers=headers)).status_code == 403
    cached_client.headers.pop("Authorization")
    assert (await cached_client.get(url)).status_code == 401


@pytest.mark.parametrize("mutation", ["remove_member", "delete_assignee"])
async def test_assignment_changes_outside_task_service_invalidate_cache(
    cached_client: AsyncClient,
    db_session: AsyncSession,
    project: Project,
    mutation: str,
) -> None:
    member = await join(db_session, project.workspace_id, WorkspaceRole.EDITOR)
    created = await cached_client.post(
        "/api/v1/tasks",
        json={"project_id": project.id, "title": "Assigned", "assignee_id": member.id},
    )
    assert created.status_code == 201
    url = f"/api/v1/projects/{project.id}/tasks"
    assert (await cached_client.get(url)).json()["items"][0]["assignee_id"] == member.id
    filtered = {"assignee_id": member.id}
    assert (await cached_client.get(url, params=filtered)).json()["total"] == 1
    if mutation == "remove_member":
        removed = await cached_client.delete(
            f"/api/v1/workspaces/{project.workspace_id}/members/{member.id}"
        )
        assert removed.status_code == 204
    else:
        await db_session.execute(
            delete(WorkspaceMember).where(WorkspaceMember.user_id == member.id)
        )
        await db_session.execute(delete(User).where(User.id == member.id))
        await db_session.flush()
    assert (await cached_client.get(url)).json()["items"][0]["assignee_id"] is None
    assert (await cached_client.get(url, params=filtered)).json()["total"] == 0


@pytest.mark.parametrize("resource", ["projects", "workspaces"])
async def test_cached_deleted_resource_returns_404(
    cached_client: AsyncClient, project: Project, resource: str
) -> None:
    url = f"/api/v1/projects/{project.id}/tasks"
    assert (await cached_client.get(url)).status_code == 200
    entity_id = project.id if resource == "projects" else project.workspace_id
    assert (
        await cached_client.delete(f"/api/v1/{resource}/{entity_id}")
    ).status_code == 204
    assert (await cached_client.get(url)).status_code == 404


async def test_rollback_and_empty_patch_keep_the_current_cache_version(
    cached_client: AsyncClient, db_session: AsyncSession, project: Project
) -> None:
    created = await cached_client.post(
        "/api/v1/tasks", json={"project_id": project.id, "title": "Original"}
    )
    task_id = created.json()["id"]
    url = f"/api/v1/projects/{project.id}/tasks"
    expected = (await cached_client.get(url)).json()
    version_query = select(Project.tasks_version).where(Project.id == project.id)
    version = await db_session.scalar(version_query)
    assert version is not None
    with pytest.raises(RuntimeError, match="Rollback"):
        async with db_session.begin_nested():
            await db_session.execute(
                update(Task).where(Task.id == task_id).values(title="Uncommitted")
            )
            assert await db_session.scalar(version_query) == version + 1
            raise RuntimeError("Rollback")
    assert await db_session.scalar(version_query) == version
    task_url = f"/api/v1/tasks/{task_id}"
    assert (await cached_client.patch(task_url, json={})).status_code == 200
    assert (
        await cached_client.patch(task_url, json={"title": None})
    ).status_code == 422
    assert await db_session.scalar(version_query) == version
    assert (await cached_client.get(url)).json() == expected


async def test_late_cache_fill_cannot_restore_stale_data(
    cached_client: AsyncClient,
    db_session: AsyncSession,
    project: Project,
    cache: TaskCache,
) -> None:
    created = await cached_client.post(
        "/api/v1/tasks", json={"project_id": project.id, "title": "Old"}
    )
    url = f"/api/v1/projects/{project.id}/tasks"
    stale = TaskPage.model_validate((await cached_client.get(url)).json())
    version = await db_session.scalar(
        select(Project.tasks_version).where(Project.id == project.id)
    )
    assert version is not None
    stale_key = cache.key(project.id, version, 1, 20, TaskFilters())
    changed = await cached_client.patch(
        f"/api/v1/tasks/{created.json()['id']}", json={"title": "Fresh"}
    )
    assert changed.status_code == 200
    await cache.set(stale_key, stale)
    assert (await cached_client.get(url)).json()["items"] == [changed.json()]


@pytest.mark.parametrize("payload", [b"invalid JSON", b'{"items": []}', b"\xff"])
async def test_corrupt_cached_payload_is_replaced_from_database(
    cached_client: AsyncClient,
    project: Project,
    cache: TaskCache,
    payload: bytes,
) -> None:
    url = f"/api/v1/projects/{project.id}/tasks"
    expected = (await cached_client.get(url)).json()
    assert cache.client is not None
    keys = [key async for key in cache.client.scan_iter(f"{cache.namespace}:*")]
    await cache.client.set(keys[0], payload)
    assert (await cached_client.get(url)).json() == expected
    cached_payload = await cache.client.get(keys[0])
    assert cached_payload is not None
    assert (
        TaskPage.model_validate_json(cached_payload).model_dump(mode="json") == expected
    )


async def test_cache_expiry_reloads_database(
    cached_client: AsyncClient,
    project: Project,
    cache: TaskCache,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = f"/api/v1/projects/{project.id}/tasks"
    expected = (await cached_client.get(url)).json()
    assert cache.client is not None
    keys = [key async for key in cache.client.scan_iter(f"{cache.namespace}:*")]
    await cache.client.pexpire(keys[0], 1)
    await anyio.sleep(0.02)
    paginate = AsyncMock(return_value=([], 0))
    monkeypatch.setattr(TaskRepository, "paginate", paginate)
    assert (await cached_client.get(url)).json() == expected
    paginate.assert_awaited_once()
    assert 0 < await cache.client.ttl(keys[0]) <= cache.ttl


async def test_redis_outage_during_write_cannot_leave_a_stale_cache(
    cached_client: AsyncClient, project: Project, cache: TaskCache
) -> None:
    created = await cached_client.post(
        "/api/v1/tasks", json={"project_id": project.id, "title": "Before outage"}
    )
    url = f"/api/v1/projects/{project.id}/tasks"
    assert (await cached_client.get(url)).json()["total"] == 1
    assert cache.client is not None
    with (
        patch.object(
            cache.client, "get", AsyncMock(side_effect=ConnectionError("Offline"))
        ),
        patch.object(cache.client, "set", AsyncMock(side_effect=RedisError("Offline"))),
    ):
        changed = await cached_client.patch(
            f"/api/v1/tasks/{created.json()['id']}", json={"title": "During outage"}
        )
        assert changed.status_code == 200
        assert (await cached_client.get(url)).json()["items"] == [changed.json()]
    assert (await cached_client.get(url)).json()["items"] == [changed.json()]


async def test_cache_can_be_disabled(test_settings: Settings) -> None:
    cache = TaskCache(test_settings)
    assert cache.client is None
    assert await cache.get("unused") is None
    await cache.set("unused", TaskPage(items=[], total=0, page=1, limit=20))
    await cache.close()


@pytest.mark.parametrize(
    "overrides",
    [
        {"redis_url": "http://localhost:6379"},
        {"cache_ttl_seconds": 0},
        {"cache_ttl_seconds": 3601},
        {"cache_namespace": ""},
        {"cache_namespace": "unsafe:*"},
        {"redis_timeout_seconds": 0},
    ],
)
def test_invalid_cache_settings_fail_fast(
    test_settings: Settings, overrides: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate(test_settings.model_dump() | overrides)


async def test_concurrent_creates_and_opposite_moves_preserve_versions(
    database_engine: AsyncEngine,
) -> None:
    schema = f"cache_concurrency_{uuid4().hex}"
    async with database_engine.begin() as connection:
        await connection.execute(CreateSchema(schema))
    try:
        async with database_engine.begin() as connection:
            await connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))

            def upgrade(sync_connection: Connection) -> None:
                config = Config(
                    str(Path(__file__).resolve().parents[1] / "alembic.ini")
                )
                config.attributes["connection"] = sync_connection
                command.upgrade(config, "head")

            await connection.run_sync(upgrade)
        async with AsyncSession(database_engine, expire_on_commit=False) as session:
            await session.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            user = User(
                email="concurrency@example.test",
                full_name="Owner",
                hashed_password=hash_password("test_password_only"),
            )
            session.add(user)
            await session.flush()
            workspace = Workspace(name="Concurrent", owner_id=user.id)
            session.add(workspace)
            await session.flush()
            projects = [
                Project(name=name, workspace_id=workspace.id) for name in ("A", "B")
            ]
            session.add_all(projects)
            await session.commit()
            first_id, second_id = [project.id for project in projects]
            user_id = user.id

        async def create_task(project_id: int) -> int:
            async with AsyncSession(database_engine, expire_on_commit=False) as session:
                await session.execute(text(f'SET LOCAL search_path TO "{schema}"'))
                task = Task(
                    project_id=project_id, title="Concurrent", created_by=user_id
                )
                session.add(task)
                await session.commit()
                return task.id

        async def move_task(task_id: int, target: int) -> None:
            async with AsyncSession(database_engine) as session:
                await session.execute(text(f'SET LOCAL search_path TO "{schema}"'))
                await session.execute(
                    update(Task).where(Task.id == task_id).values(project_id=target)
                )
                await session.commit()

        with anyio.fail_after(10):
            first_task, _ = await asyncio.gather(
                create_task(first_id), create_task(first_id)
            )
            second_task = await create_task(second_id)
            await asyncio.gather(
                move_task(first_task, second_id), move_task(second_task, first_id)
            )
        async with AsyncSession(database_engine) as session:
            await session.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            versions = await session.scalars(
                select(Project.tasks_version).order_by(Project.id)
            )
            assert list(versions) == [4, 3]
    finally:
        async with database_engine.begin() as connection:
            await connection.execute(DropSchema(schema, cascade=True))
