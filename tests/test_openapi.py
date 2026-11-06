from fastapi.testclient import TestClient


def test_openapi_documents_crud_errors_and_patch_nullability(
    client: TestClient,
) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    document = response.json()
    paths = document["paths"]
    assert set(paths["/api/v1/tasks"]) == {"get", "post"}
    task_operations = paths["/api/v1/tasks/{task_id}"]
    assert set(task_operations) == {"get", "patch", "delete"}
    for operation in task_operations.values():
        assert "404" in operation["responses"]
        assert "422" in operation["responses"]

    schema = document["components"]["schemas"]["TaskUpdate"]
    assert not schema.get("required")
    properties = schema["properties"]
    assert properties["title"]["type"] == "string"
    assert "$ref" in properties["status"]
    assert "$ref" in properties["priority"]
    for field in ["description", "due_date"]:
        assert {"type": "null"} in properties[field]["anyOf"]
    assert schema["additionalProperties"] is False


def test_swagger_and_redoc_are_available(client: TestClient) -> None:
    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200
