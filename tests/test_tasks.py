from datetime import datetime
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

TASKS_URL = "/api/v1/tasks"


@pytest.fixture
def task(client: TestClient) -> dict[str, Any]:
    response = client.post(
        TASKS_URL,
        json={
            "title": "Original task",
            "description": "Keep this description",
            "due_date": "2027-01-15",
        },
    )
    assert response.status_code == 201
    return cast(dict[str, Any], response.json())


def test_task_crud(client: TestClient) -> None:
    assert client.get(TASKS_URL).json() == []

    response = client.post(TASKS_URL, json={"title": "  Learn FastAPI  "})
    assert response.status_code == 201
    created = response.json()
    UUID(created["id"])
    assert created["title"] == "Learn FastAPI"
    assert created["status"] == "TODO"
    assert created["priority"] == "MEDIUM"
    assert created["description"] is None
    assert created["due_date"] is None
    assert datetime.fromisoformat(created["created_at"]).utcoffset() is not None
    task_url = f"{TASKS_URL}/{created['id']}"
    assert response.headers["location"] == task_url

    assert client.get(task_url).json() == created
    assert client.get(TASKS_URL).json() == [created]

    response = client.patch(
        task_url,
        json={
            "title": "  Finish Day 1  ",
            "status": "IN_PROGRESS",
            "priority": "HIGH",
        },
    )
    assert response.status_code == 200
    updated = response.json()
    assert updated["id"] == created["id"]
    assert updated["created_at"] == created["created_at"]
    assert updated["title"] == "Finish Day 1"
    assert updated["status"] == "IN_PROGRESS"
    assert updated["priority"] == "HIGH"
    assert client.get(task_url).json() == updated

    response = client.delete(task_url)
    assert response.status_code == 204
    assert response.content == b""
    assert client.get(TASKS_URL).json() == []
    assert client.get(task_url).status_code == 404


@pytest.mark.parametrize("field", ["title", "status", "priority"])
def test_patch_rejects_null_without_corrupting_storage(
    client: TestClient, task: dict[str, Any], field: str
) -> None:
    task_url = f"{TASKS_URL}/{task['id']}"
    payload = {"description": "Must not be saved", field: None}

    response = client.patch(task_url, json=payload)

    assert response.status_code == 422
    assert any(error["loc"] == ["body", field] for error in response.json()["detail"])
    response = client.get(task_url)
    assert response.status_code == 200
    assert response.json() == task
    response = client.get(TASKS_URL)
    assert response.status_code == 200
    assert response.json() == [task]


def test_patch_distinguishes_omission_from_nullable_fields(
    client: TestClient, task: dict[str, Any]
) -> None:
    task_url = f"{TASKS_URL}/{task['id']}"
    response = client.patch(task_url, json={"status": "DONE"})
    assert response.status_code == 200
    updated = response.json()
    assert updated["title"] == task["title"]
    assert updated["description"] == task["description"]
    assert updated["due_date"] == task["due_date"]

    response = client.patch(task_url, json={"description": None, "due_date": None})
    assert response.status_code == 200
    updated = response.json()
    assert updated["description"] is None
    assert updated["due_date"] is None
    assert updated["title"] == task["title"]
    assert updated["status"] == "DONE"
    assert client.get(task_url).json() == updated


def test_empty_patch_is_a_no_op(client: TestClient, task: dict[str, Any]) -> None:
    response = client.patch(f"{TASKS_URL}/{task['id']}", json={})
    assert response.status_code == 200
    assert response.json() == task


@pytest.mark.parametrize("title", ["", " ", "\t\n  ", "x" * 201])
def test_invalid_title_is_rejected_on_create_and_update(
    client: TestClient, task: dict[str, Any], title: str
) -> None:
    assert client.post(TASKS_URL, json={"title": title}).status_code == 422
    response = client.patch(f"{TASKS_URL}/{task['id']}", json={"title": title})
    assert response.status_code == 422
    assert client.get(TASKS_URL).json() == [task]


@pytest.mark.parametrize("title", ["x", "x" * 200])
def test_title_length_boundaries_are_shared_by_create_and_update(
    client: TestClient, title: str
) -> None:
    response = client.post(TASKS_URL, json={"title": f"  {title}  "})
    assert response.status_code == 201
    task_id = response.json()["id"]
    assert response.json()["title"] == title
    response = client.patch(f"{TASKS_URL}/{task_id}", json={"title": f"\t{title}\n"})
    assert response.status_code == 200
    assert response.json()["title"] == title


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"title": None},
        {"title": 123},
        {"title": "Valid", "status": None},
        {"title": "Valid", "priority": None},
        {"title": "Valid", "status": "UNKNOWN"},
        {"title": "Valid", "priority": "UNKNOWN"},
        {"title": "Valid", "due_date": "invalid-date"},
        {"title": "Valid", "description": "x" * 5_001},
        {"title": "Valid", "unexpected": True},
        {"title": "Valid", "id": str(uuid4())},
        {"title": "Valid", "created_at": "2026-01-01T00:00:00Z"},
        {"title": "Valid", "updated_at": "2026-01-01T00:00:00Z"},
    ],
)
def test_invalid_create_does_not_write_data(
    client: TestClient, payload: dict[str, Any]
) -> None:
    assert client.post(TASKS_URL, json=payload).status_code == 422
    assert client.get(TASKS_URL).json() == []


@pytest.mark.parametrize(
    "payload",
    [
        {"title": 123},
        {"status": "UNKNOWN"},
        {"priority": "UNKNOWN"},
        {"due_date": "2027-02-30"},
        {"description": "x" * 5_001},
        {"unexpected": True},
        {"id": str(uuid4())},
        {"created_at": "2026-01-01T00:00:00Z"},
        {"updated_at": "2026-01-01T00:00:00Z"},
    ],
)
def test_invalid_patch_is_atomic(
    client: TestClient, task: dict[str, Any], payload: dict[str, Any]
) -> None:
    task_url = f"{TASKS_URL}/{task['id']}"
    assert client.patch(task_url, json=payload).status_code == 422
    assert client.get(task_url).json() == task


@pytest.mark.parametrize("method", ["GET", "PATCH", "DELETE"])
def test_missing_task_has_consistent_error(client: TestClient, method: str) -> None:
    response = client.request(method, f"{TASKS_URL}/{uuid4()}", json={})
    assert response.status_code == 404
    assert response.json() == {"detail": "Task not found"}


@pytest.mark.parametrize("method", ["GET", "PATCH", "DELETE"])
def test_invalid_task_id_is_rejected(client: TestClient, method: str) -> None:
    response = client.request(method, f"{TASKS_URL}/not-a-uuid", json={})
    assert response.status_code == 422


def test_malformed_json_is_rejected(client: TestClient) -> None:
    response = client.post(
        TASKS_URL, content='{"title":', headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422
    assert client.get(TASKS_URL).json() == []
