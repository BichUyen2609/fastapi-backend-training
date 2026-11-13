import pytest
from httpx2 import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.enums import UserRole, WorkspaceRole
from app.models.entities import Project
from tests.test_auth import bearer, new_user
from tests.test_workspaces import join

pytestmark = pytest.mark.anyio


async def test_project_crud_in_workspace(client: AsyncClient, project: Project) -> None:
    base = f"/api/v1/workspaces/{project.workspace_id}/projects"
    response = await client.post(
        base, json={"name": "  Backend  ", "description": "API"}
    )
    assert response.status_code == 201
    created = response.json()
    assert created["name"] == "Backend"
    assert created["status"] == "ACTIVE"
    assert created["workspace_id"] == project.workspace_id
    url = f"/api/v1/projects/{created['id']}"
    assert response.headers["location"] == url
    assert (await client.get(url)).json() == created
    updated = await client.patch(url, json={"description": None, "name": "Core"})
    assert updated.status_code == 200
    assert updated.json()["description"] is None
    assert updated.json()["name"] == "Core"
    assert (await client.patch(url, json={})).json() == updated.json()
    page = await client.get(base, params={"limit": 1})
    assert page.json()["total"] == 2 and len(page.json()["items"]) == 1
    assert (await client.delete(url)).status_code == 204
    assert (await client.get(url)).status_code == 404


async def test_duplicate_project_name_is_409(
    client: AsyncClient, project: Project
) -> None:
    base = f"/api/v1/workspaces/{project.workspace_id}/projects"
    response = await client.post(base, json={"name": project.name})
    assert response.status_code == 409
    assert response.json()["detail"] == "Project name already exists in this workspace"
    other = await client.post(base, json={"name": "Unique"})
    assert (
        await client.patch(
            f"/api/v1/projects/{other.json()['id']}", json={"name": project.name}
        )
    ).status_code == 409


@pytest.mark.parametrize(
    "payload",
    [{"name": None}, {"status": None}, {"status": "DELETED"}, {"workspace_id": 1}],
)
async def test_project_update_validation(
    client: AsyncClient, project: Project, payload: dict[str, object]
) -> None:
    assert (
        await client.patch(f"/api/v1/projects/{project.id}", json=payload)
    ).status_code == 422


async def test_archive_blocks_task_writes_until_restored(
    client: AsyncClient, project: Project
) -> None:
    created = await client.post(
        "/api/v1/tasks", json={"project_id": project.id, "title": "Before"}
    )
    task_url = f"/api/v1/tasks/{created.json()['id']}"
    archived = await client.post(f"/api/v1/projects/{project.id}/archive")
    assert archived.status_code == 200 and archived.json()["status"] == "ARCHIVED"
    blocked = await client.post(
        "/api/v1/tasks", json={"project_id": project.id, "title": "After"}
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == "Project is archived"
    assert (await client.patch(task_url, json={"title": "x"})).status_code == 409
    assert (await client.delete(task_url)).status_code == 409
    assert (await client.get(task_url)).status_code == 200
    listed = await client.get(
        f"/api/v1/workspaces/{project.workspace_id}/projects",
        params={"status": "ARCHIVED"},
    )
    assert [item["id"] for item in listed.json()["items"]] == [project.id]
    restored = await client.post(f"/api/v1/projects/{project.id}/restore")
    assert restored.json()["status"] == "ACTIVE"
    assert (await client.patch(task_url, json={"title": "x"})).status_code == 200


async def test_moving_task_into_archived_project_is_blocked(
    client: AsyncClient, project: Project
) -> None:
    target = await client.post(
        f"/api/v1/workspaces/{project.workspace_id}/projects", json={"name": "Old"}
    )
    target_id = target.json()["id"]
    await client.post(f"/api/v1/projects/{target_id}/archive")
    created = await client.post(
        "/api/v1/tasks", json={"project_id": project.id, "title": "Move me"}
    )
    assert (
        await client.patch(
            f"/api/v1/tasks/{created.json()['id']}", json={"project_id": target_id}
        )
    ).status_code == 409


@pytest.mark.parametrize(
    "role,read,write,delete",
    [
        (WorkspaceRole.VIEWER, 200, 403, 403),
        (WorkspaceRole.EDITOR, 200, 200, 403),
        (WorkspaceRole.OWNER, 200, 200, 204),
        (None, 403, 403, 403),
    ],
)
async def test_project_permissions_follow_workspace_role(
    client: AsyncClient,
    db_session: AsyncSession,
    project: Project,
    test_settings: Settings,
    role: WorkspaceRole | None,
    read: int,
    write: int,
    delete: int,
) -> None:
    user = (
        await join(db_session, project.workspace_id, role)
        if role is not None
        else await new_user(db_session)
    )
    headers = bearer(user.id, test_settings)
    url = f"/api/v1/projects/{project.id}"
    base = f"/api/v1/workspaces/{project.workspace_id}/projects"
    assert (await client.get(url, headers=headers)).status_code == read
    assert (await client.get(base, headers=headers)).status_code == read
    assert (
        await client.patch(url, json={"description": "x"}, headers=headers)
    ).status_code == write
    assert (await client.post(f"{url}/archive", headers=headers)).status_code == write
    expected_create = 201 if write == 200 else 403
    assert (
        await client.post(base, json={"name": "By member"}, headers=headers)
    ).status_code == expected_create
    assert (await client.delete(url, headers=headers)).status_code == delete


async def test_admin_can_manage_any_project(
    client: AsyncClient,
    db_session: AsyncSession,
    project: Project,
    test_settings: Settings,
) -> None:
    admin = await new_user(db_session, UserRole.ADMIN)
    headers = bearer(admin.id, test_settings)
    assert (
        await client.post(
            f"/api/v1/workspaces/{project.workspace_id}/projects",
            json={"name": "By admin"},
            headers=headers,
        )
    ).status_code == 201
    assert (
        await client.delete(f"/api/v1/projects/{project.id}", headers=headers)
    ).status_code == 204


async def test_missing_project_and_workspace_are_404(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/projects/2000000000")).status_code == 404
    assert (
        await client.post(
            "/api/v1/workspaces/2000000000/projects", json={"name": "Lost"}
        )
    ).status_code == 404
    assert (
        await client.get("/api/v1/workspaces/2000000000/projects")
    ).status_code == 404
