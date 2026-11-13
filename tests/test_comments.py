from typing import Any

import pytest
from httpx2 import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.enums import UserRole, WorkspaceRole
from app.models.entities import Project, User
from tests.test_auth import bearer, new_user
from tests.test_labels import make_task
from tests.test_workspaces import join

pytestmark = pytest.mark.anyio


async def add_comment(
    client: AsyncClient,
    task_id: int,
    content: str = "Looks good",
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    response = await client.post(
        f"/api/v1/tasks/{task_id}/comments",
        json={"content": content},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


async def test_add_and_list_comments(
    client: AsyncClient, project: Project, current_user: User
) -> None:
    task = await make_task(client, project.id)
    first = await add_comment(client, task["id"], "  First  ")
    assert first["content"] == "First"
    assert first["author_id"] == current_user.id
    assert first["task_id"] == task["id"]
    await add_comment(client, task["id"], "Second")
    page = await client.get(f"/api/v1/tasks/{task['id']}/comments", params={"limit": 1})
    assert page.status_code == 200
    assert page.json()["total"] == 2 and len(page.json()["items"]) == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"content": ""},
        {"content": "   "},
        {"content": "x" * 4001},
        {},
        {"author_id": 1},
    ],
)
async def test_comment_validation(
    client: AsyncClient, project: Project, payload: dict[str, Any]
) -> None:
    task = await make_task(client, project.id)
    response = await client.post(f"/api/v1/tasks/{task['id']}/comments", json=payload)
    assert response.status_code == 422


async def test_missing_task_and_comment_are_404(client: AsyncClient) -> None:
    assert (
        await client.post("/api/v1/tasks/2000000000/comments", json={"content": "x"})
    ).status_code == 404
    assert (await client.get("/api/v1/tasks/2000000000/comments")).status_code == 404
    assert (await client.delete("/api/v1/comments/2000000000")).status_code == 404


@pytest.mark.parametrize(
    "role,read,write",
    [
        (WorkspaceRole.VIEWER, 200, 403),
        (WorkspaceRole.EDITOR, 200, 201),
        (None, 403, 403),
    ],
)
async def test_comment_permissions(
    client: AsyncClient,
    db_session: AsyncSession,
    project: Project,
    test_settings: Settings,
    role: WorkspaceRole | None,
    read: int,
    write: int,
) -> None:
    task = await make_task(client, project.id)
    user = (
        await join(db_session, project.workspace_id, role)
        if role is not None
        else await new_user(db_session)
    )
    headers = bearer(user.id, test_settings)
    url = f"/api/v1/tasks/{task['id']}/comments"
    assert (await client.get(url, headers=headers)).status_code == read
    assert (
        await client.post(url, json={"content": "Hi"}, headers=headers)
    ).status_code == write


async def test_only_author_owner_or_admin_can_delete(
    client: AsyncClient,
    db_session: AsyncSession,
    project: Project,
    test_settings: Settings,
) -> None:
    task = await make_task(client, project.id)
    author = await join(db_session, project.workspace_id, WorkspaceRole.EDITOR)
    editor = await join(db_session, project.workspace_id, WorkspaceRole.EDITOR)
    admin = await new_user(db_session, UserRole.ADMIN)
    author_headers = bearer(author.id, test_settings)
    own = await add_comment(client, task["id"], headers=author_headers)
    assert (
        await client.delete(
            f"/api/v1/comments/{own['id']}", headers=bearer(editor.id, test_settings)
        )
    ).status_code == 403
    assert (
        await client.delete(f"/api/v1/comments/{own['id']}", headers=author_headers)
    ).status_code == 204
    by_owner = await add_comment(client, task["id"], headers=author_headers)
    assert (
        await client.delete(f"/api/v1/comments/{by_owner['id']}")
    ).status_code == 204
    by_admin = await add_comment(client, task["id"], headers=author_headers)
    assert (
        await client.delete(
            f"/api/v1/comments/{by_admin['id']}",
            headers=bearer(admin.id, test_settings),
        )
    ).status_code == 204


async def test_archived_project_comments_are_read_only(
    client: AsyncClient, project: Project
) -> None:
    task = await make_task(client, project.id)
    comment = await add_comment(client, task["id"])
    await client.post(f"/api/v1/projects/{project.id}/archive")
    assert (
        await client.post(
            f"/api/v1/tasks/{task['id']}/comments", json={"content": "Late"}
        )
    ).status_code == 409
    assert (await client.delete(f"/api/v1/comments/{comment['id']}")).status_code == 409
    assert (await client.get(f"/api/v1/tasks/{task['id']}/comments")).status_code == 200


async def test_task_deletion_removes_comments(
    client: AsyncClient, project: Project
) -> None:
    task = await make_task(client, project.id)
    comment = await add_comment(client, task["id"])
    await client.delete(f"/api/v1/tasks/{task['id']}")
    assert (await client.delete(f"/api/v1/comments/{comment['id']}")).status_code == 404
