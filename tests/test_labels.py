from typing import Any

import pytest
from httpx2 import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.enums import WorkspaceRole
from app.models.entities import Project
from tests.test_auth import bearer, new_user
from tests.test_workspaces import join

pytestmark = pytest.mark.anyio


async def make_label(
    client: AsyncClient, project_id: int, name: str = "Bug", color: str = "#D73A4A"
) -> dict[str, Any]:
    response = await client.post(
        f"/api/v1/projects/{project_id}/labels", json={"name": name, "color": color}
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


async def make_task(client: AsyncClient, project_id: int) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/tasks", json={"project_id": project_id, "title": "Labelled"}
    )
    assert response.status_code == 201
    return dict(response.json())


async def test_label_crud(client: AsyncClient, project: Project) -> None:
    label = await make_label(client, project.id)
    assert label["color"] == "#d73a4a"
    assert label["project_id"] == project.id
    await make_label(client, project.id, "Accessibility", "#0e8a16")
    listed = await client.get(f"/api/v1/projects/{project.id}/labels")
    assert [item["name"] for item in listed.json()] == ["Accessibility", "Bug"]
    url = f"/api/v1/labels/{label['id']}"
    updated = await client.patch(url, json={"name": "Defect"})
    assert updated.status_code == 200
    assert updated.json()["name"] == "Defect" and updated.json()["color"] == "#d73a4a"
    assert (await client.patch(url, json={})).json() == updated.json()
    assert (await client.delete(url)).status_code == 204
    assert (await client.delete(url)).status_code == 404


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "x", "color": "red"},
        {"name": "x", "color": "#12345"},
        {"name": "x", "color": "#GGGGGG"},
        {"name": " ", "color": "#ffffff"},
        {"name": "x"},
        {"name": "x", "color": "#ffffff", "project_id": 1},
    ],
)
async def test_label_validation(
    client: AsyncClient, project: Project, payload: dict[str, str]
) -> None:
    response = await client.post(f"/api/v1/projects/{project.id}/labels", json=payload)
    assert response.status_code == 422


async def test_duplicate_label_name_is_409(
    client: AsyncClient, project: Project
) -> None:
    await make_label(client, project.id)
    response = await client.post(
        f"/api/v1/projects/{project.id}/labels",
        json={"name": "Bug", "color": "#000000"},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "Label name already exists in this project"
    other = await make_label(client, project.id, "Other")
    assert (
        await client.patch(f"/api/v1/labels/{other['id']}", json={"name": "Bug"})
    ).status_code == 409


async def test_attach_and_detach_labels(client: AsyncClient, project: Project) -> None:
    label = await make_label(client, project.id)
    task = await make_task(client, project.id)
    url = f"/api/v1/tasks/{task['id']}/labels/{label['id']}"
    attached = await client.post(url)
    assert attached.status_code == 200
    assert [item["id"] for item in attached.json()] == [label["id"]]
    assert (await client.post(url)).json() == attached.json()
    listed = await client.get(f"/api/v1/tasks/{task['id']}/labels")
    assert listed.json() == attached.json()
    assert (await client.delete(url)).status_code == 204
    assert (await client.delete(url)).status_code == 204
    assert (await client.get(f"/api/v1/tasks/{task['id']}/labels")).json() == []


async def test_label_from_other_project_cannot_be_attached(
    client: AsyncClient, project: Project
) -> None:
    other = await client.post(
        f"/api/v1/workspaces/{project.workspace_id}/projects", json={"name": "Other"}
    )
    foreign_label = await make_label(client, other.json()["id"])
    task = await make_task(client, project.id)
    response = await client.post(
        f"/api/v1/tasks/{task['id']}/labels/{foreign_label['id']}"
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Label must belong to the task's project"
    assert (
        await client.post(f"/api/v1/tasks/{task['id']}/labels/2000000000")
    ).status_code == 404
    assert (
        await client.post(f"/api/v1/tasks/2000000000/labels/{foreign_label['id']}")
    ).status_code == 404


async def test_moving_task_clears_labels_and_deleting_label_unlinks(
    client: AsyncClient, project: Project
) -> None:
    label = await make_label(client, project.id)
    task = await make_task(client, project.id)
    await client.post(f"/api/v1/tasks/{task['id']}/labels/{label['id']}")
    target = await client.post(
        f"/api/v1/workspaces/{project.workspace_id}/projects", json={"name": "Target"}
    )
    moved = await client.patch(
        f"/api/v1/tasks/{task['id']}", json={"project_id": target.json()["id"]}
    )
    assert moved.status_code == 200
    assert (await client.get(f"/api/v1/tasks/{task['id']}/labels")).json() == []
    second = await make_task(client, project.id)
    await client.post(f"/api/v1/tasks/{second['id']}/labels/{label['id']}")
    await client.delete(f"/api/v1/labels/{label['id']}")
    assert (await client.get(f"/api/v1/tasks/{second['id']}/labels")).json() == []


@pytest.mark.parametrize(
    "role,read,write",
    [
        (WorkspaceRole.VIEWER, 200, 403),
        (WorkspaceRole.EDITOR, 200, 201),
        (None, 403, 403),
    ],
)
async def test_label_permissions(
    client: AsyncClient,
    db_session: AsyncSession,
    project: Project,
    test_settings: Settings,
    role: WorkspaceRole | None,
    read: int,
    write: int,
) -> None:
    label = await make_label(client, project.id)
    task = await make_task(client, project.id)
    user = (
        await join(db_session, project.workspace_id, role)
        if role is not None
        else await new_user(db_session)
    )
    headers = bearer(user.id, test_settings)
    assert (
        await client.get(f"/api/v1/projects/{project.id}/labels", headers=headers)
    ).status_code == read
    assert (
        await client.get(f"/api/v1/tasks/{task['id']}/labels", headers=headers)
    ).status_code == read
    assert (
        await client.post(
            f"/api/v1/projects/{project.id}/labels",
            json={"name": "Member", "color": "#ffffff"},
            headers=headers,
        )
    ).status_code == write
    expected = 200 if write == 201 else 403
    assert (
        await client.post(
            f"/api/v1/tasks/{task['id']}/labels/{label['id']}", headers=headers
        )
    ).status_code == expected
    assert (
        await client.patch(
            f"/api/v1/labels/{label['id']}", json={"name": "x"}, headers=headers
        )
    ).status_code == expected


async def test_archived_project_labels_are_read_only(
    client: AsyncClient, project: Project
) -> None:
    label = await make_label(client, project.id)
    task = await make_task(client, project.id)
    await client.post(f"/api/v1/projects/{project.id}/archive")
    assert (
        await client.post(
            f"/api/v1/projects/{project.id}/labels",
            json={"name": "Late", "color": "#ffffff"},
        )
    ).status_code == 409
    assert (
        await client.post(f"/api/v1/tasks/{task['id']}/labels/{label['id']}")
    ).status_code == 409
    assert (
        await client.get(f"/api/v1/projects/{project.id}/labels")
    ).status_code == 200
