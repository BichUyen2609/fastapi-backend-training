import pytest
from httpx2 import AsyncClient

pytestmark = pytest.mark.anyio


async def test_openapi_documents_crud_errors_and_patch_nullability(
    client: AsyncClient,
) -> None:
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    document = response.json()
    paths = document["paths"]
    assert set(paths["/api/v1/tasks"]) == {"get", "post"}
    task_operations = paths["/api/v1/tasks/{task_id}"]
    assert set(task_operations) == {"get", "patch", "delete"}
    for operation in task_operations.values():
        assert "404" in operation["responses"]
        assert "409" in operation["responses"]
        assert "422" in operation["responses"]

    schema = document["components"]["schemas"]["TaskUpdate"]
    assert not schema.get("required")
    properties = schema["properties"]
    assert properties["title"]["type"] == "string"
    assert "$ref" in properties["status"]
    assert "$ref" in properties["priority"]
    for field in ["description", "due_date", "assignee_id"]:
        assert {"type": "null"} in properties[field]["anyOf"]
    assert schema["additionalProperties"] is False


async def test_swagger_and_redoc_are_available(client: AsyncClient) -> None:
    assert (await client.get("/docs")).status_code == 200
    assert (await client.get("/redoc")).status_code == 200
