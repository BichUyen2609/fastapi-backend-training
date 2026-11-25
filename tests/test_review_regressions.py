from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx2 import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.api.dependencies import get_session
from app.core.config import Settings
from app.core.enums import WorkspaceRole
from app.models.entities import Project, User
from tests.test_auth import PASSWORD, bearer, registration
from tests.test_workspaces import join

pytestmark = pytest.mark.anyio


async def test_registration_joins_an_existing_request_transaction(
    application: FastAPI, client: AsyncClient, connection: AsyncConnection
) -> None:
    async def session_with_prior_read() -> AsyncIterator[AsyncSession]:
        async with AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        ) as session:
            await session.execute(select(User.id).limit(1))
            assert session.in_transaction()
            yield session

    application.dependency_overrides[get_session] = session_with_prior_read
    payload = registration()
    response = await client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201
    user_id = response.json()["id"]
    duplicate = await client.post("/api/v1/auth/register", json=payload)
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "Email already registered"
    login = await client.post(
        "/api/v1/auth/login", data={"username": payload["email"], "password": PASSWORD}
    )
    assert login.status_code == 200
    profile = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": "Bearer " + login.json()["access_token"]},
    )
    assert profile.status_code == 200
    assert profile.json()["id"] == user_id


@pytest.mark.parametrize("role", [WorkspaceRole.VIEWER, WorkspaceRole.EDITOR])
@pytest.mark.parametrize("archived", [False, True])
async def test_comment_author_policy_preserves_viewer_exception_and_archive_guard(
    client: AsyncClient,
    db_session: AsyncSession,
    project: Project,
    test_settings: Settings,
    role: WorkspaceRole,
    archived: bool,
) -> None:
    author = await join(db_session, project.workspace_id, WorkspaceRole.EDITOR)
    author_headers = bearer(author.id, test_settings)
    task = await client.post(
        "/api/v1/tasks", json={"project_id": project.id, "title": "Review permissions"}
    )
    assert task.status_code == 201
    comments_url = f"/api/v1/tasks/{task.json()['id']}/comments"
    own = await client.post(
        comments_url, json={"content": "Author"}, headers=author_headers
    )
    other = await client.post(comments_url, json={"content": "Owner"})
    assert own.status_code == other.status_code == 201
    membership = await client.patch(
        f"/api/v1/workspaces/{project.workspace_id}/members/{author.id}",
        json={"role": role.value},
    )
    assert membership.status_code == 200
    if archived:
        assert (
            await client.post(f"/api/v1/projects/{project.id}/archive")
        ).status_code == 200
    forbidden = await client.delete(
        f"/api/v1/comments/{other.json()['id']}", headers=author_headers
    )
    assert forbidden.status_code == 403
    deleted = await client.delete(
        f"/api/v1/comments/{own.json()['id']}", headers=author_headers
    )
    assert deleted.status_code == (409 if archived else 204)
    listed = await client.get(comments_url)
    assert listed.status_code == 200
    assert listed.json()["total"] == (2 if archived else 1)


@pytest.mark.parametrize(
    "role,expected", [(WorkspaceRole.VIEWER, 403), (WorkspaceRole.EDITOR, 200)]
)
async def test_archived_project_management_keeps_its_own_role_policy(
    client: AsyncClient,
    db_session: AsyncSession,
    project: Project,
    test_settings: Settings,
    role: WorkspaceRole,
    expected: int,
) -> None:
    member = await join(db_session, project.workspace_id, role)
    headers = bearer(member.id, test_settings)
    url = f"/api/v1/projects/{project.id}"
    assert (await client.post(url + "/archive")).status_code == 200
    assert (
        await client.patch(url, json={"name": "Reviewed"}, headers=headers)
    ).status_code == expected
    assert (
        await client.post(url + "/restore", headers=headers)
    ).status_code == expected
    assert (await client.post(url + "/archive")).status_code == 200
    assert (await client.delete(url)).status_code == 204


@pytest.mark.parametrize("resource", ["labels", "comments"])
async def test_missing_task_keeps_domain_error_contract(
    client: AsyncClient, resource: str
) -> None:
    response = await client.get(f"/api/v1/tasks/2000000000/{resource}")
    assert response.status_code == 404
    assert response.json()["detail"] == "Task not found"
    assert response.json()["code"] == "NOT_FOUND"
