from datetime import datetime, timedelta
from typing import Any, cast

import pytest
from httpx2 import AsyncClient

TASKS_URL = "/api/v1/tasks"
pytestmark = pytest.mark.anyio


@pytest.fixture
async def task(client: AsyncClient, references: dict[str, int]) -> dict[str, Any]:
    response = await client.post(
        TASKS_URL,
        json=references
        | {
            "title": "Original task",
            "description": "Keep this description",
            "due_date": "2027-01-15",
        },
    )
    assert response.status_code == 201
    return cast(dict[str, Any], response.json())


async def test_task_crud(client: AsyncClient, references: dict[str, int]) -> None:
    params = {"project_id": references["project_id"]}
    assert (await client.get(TASKS_URL, params=params)).json()["items"] == []
    response = await client.post(
        TASKS_URL, json=references | {"title": "  Learn FastAPI  "}
    )
    assert response.status_code == 201
    created = response.json()
    assert isinstance(created["id"], int) and created["id"] > 0
    assert created["title"] == "Learn FastAPI"
    assert created["status"] == "TODO"
    assert created["priority"] == "MEDIUM"
    assert created["description"] is None
    assert datetime.fromisoformat(created["created_at"]).utcoffset() == timedelta(0)
    task_url = f"{TASKS_URL}/{created['id']}"
    assert response.headers["location"] == task_url
    assert (await client.get(task_url)).json() == created
    page = (await client.get(TASKS_URL, params=params)).json()
    assert page["items"] == [created]
    assert page["total"] == 1
    response = await client.patch(
        task_url,
        json={"title": "  Finish Day 2  ", "status": "IN_PROGRESS", "priority": "HIGH"},
    )
    assert response.status_code == 200
    updated = response.json()
    assert updated["created_at"] == created["created_at"]
    assert updated["title"] == "Finish Day 2"
    assert updated["status"] == "IN_PROGRESS"
    assert updated["priority"] == "HIGH"
    assert (await client.get(task_url)).json() == updated
    response = await client.delete(task_url)
    assert response.status_code == 204
    assert response.content == b""
    assert (await client.get(TASKS_URL, params=params)).json()["total"] == 0
    assert (await client.get(task_url)).status_code == 404


@pytest.mark.parametrize("field", ["title", "status", "priority", "project_id"])
async def test_patch_rejects_null_without_corrupting_storage(
    client: AsyncClient, task: dict[str, Any], field: str
) -> None:
    task_url = f"{TASKS_URL}/{task['id']}"
    response = await client.patch(
        task_url, json={"description": "Must not save", field: None}
    )
    assert response.status_code == 422
    assert any(error["loc"] == ["body", field] for error in response.json()["detail"])
    assert (await client.get(task_url)).json() == task
    response = await client.get(TASKS_URL, params={"project_id": task["project_id"]})
    assert response.status_code == 200
    assert response.json()["items"] == [task]


async def test_patch_distinguishes_omission_and_explicit_null(
    client: AsyncClient, task: dict[str, Any]
) -> None:
    task_url = f"{TASKS_URL}/{task['id']}"
    response = await client.patch(
        task_url, json={"status": "DONE", "assignee_id": task["created_by"]}
    )
    assert response.status_code == 200
    updated = response.json()
    assert updated["description"] == task["description"]
    assert updated["due_date"] == task["due_date"]
    assert updated["assignee_id"] == task["created_by"]
    response = await client.patch(
        task_url, json={"description": None, "due_date": None, "assignee_id": None}
    )
    assert response.status_code == 200
    updated = response.json()
    assert updated["description"] is None
    assert updated["due_date"] is None
    assert updated["assignee_id"] is None
    assert updated["title"] == task["title"]
    assert updated["status"] == "DONE"
    assert (await client.get(task_url)).json() == updated


async def test_empty_patch_is_no_op(client: AsyncClient, task: dict[str, Any]) -> None:
    response = await client.patch(f"{TASKS_URL}/{task['id']}", json={})
    assert response.status_code == 200
    assert response.json() == task


@pytest.mark.parametrize("title", ["", " ", "\t\n  ", "x" * 201])
async def test_invalid_title_does_not_write(
    client: AsyncClient, task: dict[str, Any], references: dict[str, int], title: str
) -> None:
    assert (
        await client.post(TASKS_URL, json=references | {"title": title})
    ).status_code == 422
    assert (
        await client.patch(f"{TASKS_URL}/{task['id']}", json={"title": title})
    ).status_code == 422
    assert (await client.get(f"{TASKS_URL}/{task['id']}")).json() == task


@pytest.mark.parametrize("title", ["x", "x" * 200])
async def test_title_length_boundaries(
    client: AsyncClient, references: dict[str, int], title: str
) -> None:
    response = await client.post(TASKS_URL, json=references | {"title": f"  {title}  "})
    assert response.status_code == 201
    task_id = response.json()["id"]
    response = await client.patch(
        f"{TASKS_URL}/{task_id}", json={"title": f"\t{title}\n"}
    )
    assert response.status_code == 200
    assert response.json()["title"] == title


@pytest.mark.parametrize(
    "payload",
    [
        {"title": None},
        {"title": 123},
        {"title": "Valid", "status": None},
        {"title": "Valid", "priority": None},
        {"title": "Valid", "status": "UNKNOWN"},
        {"title": "Valid", "priority": "UNKNOWN"},
        {"title": "Valid", "due_date": "invalid"},
        {"title": "Valid", "description": "x" * 5_001},
        {"title": "Valid", "unexpected": True},
        {"title": "Valid", "id": 123},
        {"title": "Valid", "created_at": "2026-01-01T00:00:00Z"},
        {"title": "Valid", "project_id": 0},
        {"title": "Valid", "created_by": -1},
        {"title": "Valid", "assignee_id": 0},
    ],
)
async def test_invalid_create_does_not_write(
    client: AsyncClient, references: dict[str, int], payload: dict[str, Any]
) -> None:
    assert (await client.post(TASKS_URL, json=references | payload)).status_code == 422
    response = await client.get(
        TASKS_URL, params={"project_id": references["project_id"]}
    )
    assert response.json()["total"] == 0


async def test_create_requires_title_and_project(client: AsyncClient) -> None:
    assert (await client.post(TASKS_URL, json={})).status_code == 422
    assert (
        await client.post(TASKS_URL, json={"title": "Missing FKs"})
    ).status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {"title": 123},
        {"status": "UNKNOWN"},
        {"priority": "UNKNOWN"},
        {"due_date": "2027-02-30"},
        {"description": "x" * 5_001},
        {"unexpected": True},
        {"id": 123},
        {"created_by": 123},
        {"created_at": "2026-01-01T00:00:00Z"},
        {"updated_at": "2026-01-01T00:00:00Z"},
        {"project_id": -1},
        {"assignee_id": 0},
    ],
)
async def test_invalid_patch_is_atomic(
    client: AsyncClient, task: dict[str, Any], payload: dict[str, Any]
) -> None:
    task_url = f"{TASKS_URL}/{task['id']}"
    assert (await client.patch(task_url, json=payload)).status_code == 422
    assert (await client.get(task_url)).json() == task


@pytest.mark.parametrize("field", ["project_id", "created_by", "assignee_id"])
async def test_nonexistent_foreign_keys_return_422(
    client: AsyncClient, references: dict[str, int], field: str
) -> None:
    payload = references | {"title": "Missing reference", field: 2_000_000_000}
    assert (await client.post(TASKS_URL, json=payload)).status_code == 422


@pytest.mark.parametrize("field", ["project_id", "assignee_id"])
async def test_invalid_patch_reference_keeps_existing_task(
    client: AsyncClient, task: dict[str, Any], field: str
) -> None:
    task_url = f"{TASKS_URL}/{task['id']}"
    response = await client.patch(
        task_url, json={field: 2_000_000_000, "title": "Do not save"}
    )
    assert response.status_code == 422
    assert (await client.get(task_url)).json() == task


@pytest.mark.parametrize("method", ["GET", "PATCH", "DELETE"])
async def test_missing_task_has_consistent_error(
    client: AsyncClient, method: str
) -> None:
    response = await client.request(method, f"{TASKS_URL}/2000000000", json={})
    assert response.status_code == 404
    assert response.json()["detail"] == "Task not found"


@pytest.mark.parametrize("task_id", ["0", "-1", "not-an-id", "99999999999999999999"])
@pytest.mark.parametrize("method", ["GET", "PATCH", "DELETE"])
async def test_invalid_task_id(client: AsyncClient, task_id: str, method: str) -> None:
    assert (
        await client.request(method, f"{TASKS_URL}/{task_id}", json={})
    ).status_code == 422


@pytest.mark.parametrize(
    "query", ["page=0", "page=-1", "limit=0", "limit=101", "project_id=0"]
)
async def test_invalid_pagination(client: AsyncClient, query: str) -> None:
    assert (await client.get(f"{TASKS_URL}?{query}")).status_code == 422


async def test_pagination_total_order_and_project_scope(
    client: AsyncClient, references: dict[str, int]
) -> None:
    created_ids = []
    for index in range(3):
        response = await client.post(
            TASKS_URL, json=references | {"title": f"Task {index}"}
        )
        assert response.status_code == 201
        created_ids.append(response.json()["id"])
    url = f"/api/v1/projects/{references['project_id']}/tasks"
    first = (await client.get(url, params={"page": 1, "limit": 2})).json()
    second = (await client.get(url, params={"page": 2, "limit": 2})).json()
    empty = (await client.get(url, params={"page": 3, "limit": 2})).json()
    assert first["total"] == second["total"] == empty["total"] == 3
    assert [item["id"] for item in first["items"] + second["items"]] == created_ids[
        ::-1
    ]
    assert empty["items"] == []
    assert first["page"] == 1 and first["limit"] == 2
    assert (await client.get("/api/v1/projects/2000000000/tasks")).status_code == 404


async def test_malformed_json(client: AsyncClient) -> None:
    response = await client.post(
        TASKS_URL, content='{"title":', headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422
