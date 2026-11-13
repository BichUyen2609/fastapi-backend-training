import pytest
from httpx2 import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.enums import UserRole, WorkspaceRole
from app.models.entities import Project, Task, User, WorkspaceMember
from tests.test_auth import bearer, new_user

pytestmark = pytest.mark.anyio


async def join(session: AsyncSession, workspace_id: int, role: WorkspaceRole) -> User:
    user = await new_user(session)
    session.add(WorkspaceMember(workspace_id=workspace_id, user_id=user.id, role=role))
    await session.flush()
    return user


async def test_create_workspace_makes_actor_owner(
    client: AsyncClient, current_user: User
) -> None:
    response = await client.post("/api/v1/workspaces", json={"name": "  Team  "})
    assert response.status_code == 201
    workspace = response.json()
    assert workspace["name"] == "Team"
    assert workspace["owner_id"] == current_user.id
    assert response.headers["location"] == f"/api/v1/workspaces/{workspace['id']}"
    members = await client.get(f"/api/v1/workspaces/{workspace['id']}/members")
    assert members.json() == [
        {
            "user_id": current_user.id,
            "email": current_user.email,
            "full_name": current_user.full_name,
            "role": "OWNER",
        }
    ]


@pytest.mark.parametrize("payload", [{}, {"name": "  "}, {"owner_id": 1, "name": "x"}])
async def test_create_workspace_validation(
    client: AsyncClient, payload: dict[str, object]
) -> None:
    assert (await client.post("/api/v1/workspaces", json=payload)).status_code == 422


async def test_list_workspaces_only_returns_visible_ones(
    client: AsyncClient,
    db_session: AsyncSession,
    project: Project,
    test_settings: Settings,
) -> None:
    viewer = await join(db_session, project.workspace_id, WorkspaceRole.VIEWER)
    outsider = await new_user(db_session)
    admin = await new_user(db_session, UserRole.ADMIN)
    own = await client.get("/api/v1/workspaces")
    assert [item["id"] for item in own.json()["items"]] == [project.workspace_id]
    seen = await client.get(
        "/api/v1/workspaces", headers=bearer(viewer.id, test_settings)
    )
    assert seen.json()["total"] == 1
    empty = await client.get(
        "/api/v1/workspaces", headers=bearer(outsider.id, test_settings)
    )
    assert empty.json() == {"items": [], "total": 0, "page": 1, "limit": 20}
    everything = await client.get(
        "/api/v1/workspaces", headers=bearer(admin.id, test_settings)
    )
    assert everything.json()["total"] >= 1


@pytest.mark.parametrize(
    "role,read,write",
    [
        (WorkspaceRole.VIEWER, 200, 403),
        (WorkspaceRole.EDITOR, 200, 403),
        (None, 403, 403),
    ],
)
async def test_workspace_crud_is_owner_only(
    client: AsyncClient,
    db_session: AsyncSession,
    project: Project,
    test_settings: Settings,
    role: WorkspaceRole | None,
    read: int,
    write: int,
) -> None:
    user = (
        await join(db_session, project.workspace_id, role)
        if role is not None
        else await new_user(db_session)
    )
    headers = bearer(user.id, test_settings)
    url = f"/api/v1/workspaces/{project.workspace_id}"
    assert (await client.get(url, headers=headers)).status_code == read
    assert (await client.get(url + "/members", headers=headers)).status_code == read
    assert (
        await client.patch(url, json={"name": "Hijack"}, headers=headers)
    ).status_code == write
    assert (await client.delete(url, headers=headers)).status_code == write


async def test_owner_and_admin_update_and_delete_workspace(
    client: AsyncClient,
    db_session: AsyncSession,
    project: Project,
    test_settings: Settings,
) -> None:
    url = f"/api/v1/workspaces/{project.workspace_id}"
    response = await client.patch(url, json={"name": "Renamed"})
    assert response.status_code == 200 and response.json()["name"] == "Renamed"
    admin = await new_user(db_session, UserRole.ADMIN)
    assert (
        await client.delete(url, headers=bearer(admin.id, test_settings))
    ).status_code == 204
    assert (await client.get(url)).status_code == 404
    assert (await client.get(f"/api/v1/projects/{project.id}")).status_code == 404


async def test_missing_workspace_is_404(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/workspaces/2000000000")).status_code == 404
    assert (await client.get("/api/v1/workspaces/0")).status_code == 422


async def test_invite_update_and_remove_member(
    client: AsyncClient,
    db_session: AsyncSession,
    project: Project,
    test_settings: Settings,
) -> None:
    invitee = await new_user(db_session)
    url = f"/api/v1/workspaces/{project.workspace_id}/members"
    response = await client.post(
        url, json={"email": invitee.email.upper(), "role": "EDITOR"}
    )
    assert response.status_code == 201
    assert response.json()["user_id"] == invitee.id
    assert response.json()["role"] == "EDITOR"
    assert (await client.post(url, json={"email": invitee.email})).status_code == 409
    headers = bearer(invitee.id, test_settings)
    assert (
        await client.get(f"/api/v1/projects/{project.id}", headers=headers)
    ).status_code == 200
    task = await client.post(
        "/api/v1/tasks",
        json={"project_id": project.id, "title": "Assigned", "assignee_id": invitee.id},
    )
    assert task.status_code == 201
    changed = await client.patch(f"{url}/{invitee.id}", json={"role": "VIEWER"})
    assert changed.status_code == 200 and changed.json()["role"] == "VIEWER"
    assert (
        await client.post(
            "/api/v1/tasks",
            json={"project_id": project.id, "title": "Denied"},
            headers=headers,
        )
    ).status_code == 403
    assert (await client.delete(f"{url}/{invitee.id}")).status_code == 204
    assert (await client.delete(f"{url}/{invitee.id}")).status_code == 404
    assert (
        await client.get(f"/api/v1/projects/{project.id}", headers=headers)
    ).status_code == 403
    refreshed = await client.get(f"/api/v1/tasks/{task.json()['id']}")
    assert refreshed.json()["assignee_id"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "missing@example.com"},
        {"email": "invalid"},
        {"role": "EDITOR"},
    ],
)
async def test_invite_rejects_unknown_users_and_bad_input(
    client: AsyncClient, project: Project, payload: dict[str, str]
) -> None:
    response = await client.post(
        f"/api/v1/workspaces/{project.workspace_id}/members", json=payload
    )
    assert response.status_code == 422


async def test_owner_role_cannot_be_granted_and_owner_is_locked(
    client: AsyncClient,
    db_session: AsyncSession,
    project: Project,
    current_user: User,
) -> None:
    invitee = await new_user(db_session)
    url = f"/api/v1/workspaces/{project.workspace_id}/members"
    assert (
        await client.post(url, json={"email": invitee.email, "role": "OWNER"})
    ).status_code == 422
    inactive = await new_user(db_session)
    inactive.is_active = False
    await db_session.flush()
    assert (await client.post(url, json={"email": inactive.email})).status_code == 422
    assert (
        await client.patch(f"{url}/{current_user.id}", json={"role": "VIEWER"})
    ).status_code == 409
    assert (await client.delete(f"{url}/{current_user.id}")).status_code == 409
    assert (
        await client.patch(f"{url}/{invitee.id}", json={"role": "EDITOR"})
    ).status_code == 404


async def test_non_owner_cannot_manage_members_but_can_leave(
    client: AsyncClient,
    db_session: AsyncSession,
    project: Project,
    test_settings: Settings,
) -> None:
    editor = await join(db_session, project.workspace_id, WorkspaceRole.EDITOR)
    viewer = await join(db_session, project.workspace_id, WorkspaceRole.VIEWER)
    outsider = await new_user(db_session)
    url = f"/api/v1/workspaces/{project.workspace_id}/members"
    headers = bearer(editor.id, test_settings)
    assert (
        await client.post(url, json={"email": outsider.email}, headers=headers)
    ).status_code == 403
    assert (
        await client.patch(
            f"{url}/{viewer.id}", json={"role": "EDITOR"}, headers=headers
        )
    ).status_code == 403
    assert (
        await client.delete(f"{url}/{viewer.id}", headers=headers)
    ).status_code == 403
    assert (
        await client.delete(f"{url}/{editor.id}", headers=headers)
    ).status_code == 204
    assert (
        await client.delete(
            f"{url}/{outsider.id}", headers=bearer(outsider.id, test_settings)
        )
    ).status_code == 403


async def test_admin_can_manage_any_workspace(
    client: AsyncClient,
    db_session: AsyncSession,
    project: Project,
    test_settings: Settings,
) -> None:
    admin = await new_user(db_session, UserRole.ADMIN)
    invitee = await new_user(db_session)
    response = await client.post(
        f"/api/v1/workspaces/{project.workspace_id}/members",
        json={"email": invitee.email, "role": "EDITOR"},
        headers=bearer(admin.id, test_settings),
    )
    assert response.status_code == 201
    roles = {
        member["user_id"]: member["role"]
        for member in (
            await client.get(f"/api/v1/workspaces/{project.workspace_id}/members")
        ).json()
    }
    assert roles[invitee.id] == "EDITOR"
    assert admin.id not in roles


async def test_member_removal_only_unassigns_tasks_in_that_workspace(
    client: AsyncClient,
    db_session: AsyncSession,
    project: Project,
    current_user: User,
) -> None:
    member = await join(db_session, project.workspace_id, WorkspaceRole.EDITOR)
    other = await client.post("/api/v1/workspaces", json={"name": "Second"})
    other_id = other.json()["id"]
    db_session.add(
        WorkspaceMember(
            workspace_id=other_id, user_id=member.id, role=WorkspaceRole.EDITOR
        )
    )
    second_project = Project(name="Second project", workspace_id=other_id)
    db_session.add(second_project)
    await db_session.flush()
    kept = Task(
        title="Kept",
        project_id=second_project.id,
        created_by=current_user.id,
        assignee_id=member.id,
    )
    db_session.add(kept)
    await db_session.flush()
    assert (
        await client.delete(
            f"/api/v1/workspaces/{project.workspace_id}/members/{member.id}"
        )
    ).status_code == 204
    assert (await client.get(f"/api/v1/tasks/{kept.id}")).json()[
        "assignee_id"
    ] == member.id
