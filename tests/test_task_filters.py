import pytest
from httpx2 import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import WorkspaceRole
from app.models.entities import Project
from tests.test_workspaces import join

pytestmark = pytest.mark.anyio


@pytest.fixture
async def seeded(
    client: AsyncClient, db_session: AsyncSession, project: Project
) -> dict[str, int]:
    member = await join(db_session, project.workspace_id, WorkspaceRole.EDITOR)
    rows = [
        ("Todo low", "TODO", "LOW", None),
        ("Doing high", "IN_PROGRESS", "HIGH", member.id),
        ("Done high", "DONE", "HIGH", member.id),
        ("Done urgent", "DONE", "URGENT", None),
    ]
    ids: dict[str, int] = {"member": member.id}
    for title, status, priority, assignee in rows:
        response = await client.post(
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
        ids[title] = response.json()["id"]
    return ids


def titles(response_json: dict[str, object]) -> set[object]:
    items = response_json["items"]
    assert isinstance(items, list)
    return {item["title"] for item in items}


@pytest.mark.parametrize("base", ["/api/v1/tasks", "/api/v1/projects/{id}/tasks"])
async def test_filters_by_status_priority_and_assignee(
    client: AsyncClient, project: Project, seeded: dict[str, int], base: str
) -> None:
    url = base.format(id=project.id)
    by_status = (await client.get(url, params={"status": "DONE"})).json()
    assert titles(by_status) == {"Done high", "Done urgent"}
    assert by_status["total"] == 2
    by_priority = (await client.get(url, params={"priority": "HIGH"})).json()
    assert titles(by_priority) == {"Doing high", "Done high"}
    by_assignee = (
        await client.get(url, params={"assignee_id": seeded["member"]})
    ).json()
    assert titles(by_assignee) == {"Doing high", "Done high"}
    combined = (
        await client.get(
            url,
            params={"status": "DONE", "priority": "HIGH", "limit": 1, "page": 1},
        )
    ).json()
    assert titles(combined) == {"Done high"}
    assert combined["total"] == 1
    assert (await client.get(url)).json()["total"] == 4


@pytest.mark.parametrize(
    "params",
    [{"status": "OPEN"}, {"priority": "CRITICAL"}, {"assignee_id": 0}],
)
async def test_invalid_filters_are_422(
    client: AsyncClient, seeded: dict[str, int], params: dict[str, str | int]
) -> None:
    response = await client.get("/api/v1/tasks", params=params)
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


async def test_openapi_documents_filters(client: AsyncClient) -> None:
    operation = (await client.get("/openapi.json")).json()["paths"]["/api/v1/tasks"][
        "get"
    ]
    names = {parameter["name"] for parameter in operation["parameters"]}
    assert {"status", "priority", "assignee_id", "page", "limit"} <= names
