from secrets import token_urlsafe
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import jwt
import pytest
from httpx2 import AsyncClient
from pydantic import SecretStr, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.constants import JWT_ALGORITHM
from app.core.enums import UserRole, WorkspaceRole
from app.core.security import create_access_token, hash_password, verify_password
from app.main import create_app
from app.models.entities import Project, Task, User, Workspace, WorkspaceMember
from app.repositories.auth import UserRepository

pytestmark = pytest.mark.anyio
PASSWORD = "Test_password_123!"


def registration(email: str | None = None) -> dict[str, str]:
    return {
        "email": email or f"{uuid4().hex}@example.com",
        "full_name": "New member",
        "password": PASSWORD,
    }


def bearer(user_id: int, settings: Settings) -> dict[str, str]:
    return {"Authorization": "Bearer " + create_access_token(user_id, settings)}


async def new_user(session: AsyncSession, role: UserRole = UserRole.MEMBER) -> User:
    user = User(
        email=f"{uuid4().hex}@example.com",
        full_name="Other user",
        hashed_password=hash_password(PASSWORD),
        role=role,
    )
    session.add(user)
    await session.flush()
    return user


async def other_project(session: AsyncSession) -> tuple[User, Project, Task]:
    owner = await new_user(session)
    workspace = Workspace(name="Other workspace", owner_id=owner.id)
    session.add(workspace)
    await session.flush()
    project = Project(name="Other project", workspace_id=workspace.id)
    session.add(project)
    await session.flush()
    task = Task(title="Other task", project_id=project.id, created_by=owner.id)
    session.add(task)
    await session.flush()
    return owner, project, task


async def test_register_hashes_password_and_login_returns_access_token(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    payload = registration()
    payload["email"] = "  " + payload["email"].upper() + "  "
    payload["full_name"] = "  New member  "
    payload["password"] = "  Password with spaces  "
    response = await client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201
    user_data = response.json()
    assert user_data["email"] == payload["email"].strip().lower()
    assert user_data["full_name"] == "New member"
    assert user_data["role"] == "MEMBER" and user_data["is_active"] is True
    assert "password" not in response.text
    stored = await db_session.get(User, user_data["id"])
    assert stored is not None
    assert stored.hashed_password != payload["password"]
    assert verify_password(payload["password"], stored.hashed_password)
    assert not verify_password(payload["password"].strip(), stored.hashed_password)
    response = await client.post(
        "/api/v1/auth/login",
        data={"username": payload["email"], "password": payload["password"]},
    )
    assert response.status_code == 200
    token = response.json()
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    assert token["token_type"] == "bearer" and token["expires_in"] > 0
    assert len(token["access_token"].split(".")) == 3
    response = await client.get(
        "/api/v1/users/me", headers={"Authorization": "Bearer " + token["access_token"]}
    )
    assert response.status_code == 200 and response.json() == user_data


async def test_duplicate_email_is_409_including_case_and_database_race(
    client: AsyncClient,
) -> None:
    payload = registration()
    assert (await client.post("/api/v1/auth/register", json=payload)).status_code == 201
    duplicate = payload | {"email": payload["email"].upper()}
    assert (
        await client.post("/api/v1/auth/register", json=duplicate)
    ).status_code == 409
    with patch.object(UserRepository, "get_by_email", new=AsyncMock(return_value=None)):
        response = await client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 409
    assert response.json()["detail"] == "Email already registered"
    assert (
        await client.post(
            "/api/v1/auth/login",
            data={"username": payload["email"], "password": PASSWORD},
        )
    ).status_code == 200


@pytest.mark.parametrize(
    "field,value",
    [("role", "ADMIN"), ("is_active", True), ("hashed_password", "forged"), ("id", 1)],
)
async def test_register_rejects_privileged_fields(
    client: AsyncClient, field: str, value: object
) -> None:
    assert (
        await client.post("/api/v1/auth/register", json=registration() | {field: value})
    ).status_code == 422


@pytest.mark.parametrize("password", ["tinyPW", "x" * 129])
async def test_password_validation_does_not_echo_password(
    client: AsyncClient, password: str
) -> None:
    response = await client.post(
        "/api/v1/auth/register", json=registration() | {"password": password}
    )
    assert response.status_code == 422
    assert password not in response.text
    assert all(
        "input" not in error
        for error in response.json()["detail"]
        if "password" in error["loc"]
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"email": "invalid"},
        {"full_name": "   "},
        {"full_name": "x" * 151},
        {"password": None},
    ],
)
async def test_invalid_registration(
    client: AsyncClient, changes: dict[str, Any]
) -> None:
    assert (
        await client.post("/api/v1/auth/register", json=registration() | changes)
    ).status_code == 422


async def test_wrong_password_and_unknown_user_have_same_error(
    client: AsyncClient, current_user: User
) -> None:
    wrong = await client.post(
        "/api/v1/auth/login",
        data={"username": current_user.email, "password": "Wrong_password"},
    )
    unknown = await client.post(
        "/api/v1/auth/login",
        data={"username": "missing@example.com", "password": "Wrong_password"},
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"]
    assert wrong.json()["detail"] == "Invalid email or password"
    assert wrong.json()["code"] == unknown.json()["code"] == "UNAUTHORIZED"
    assert wrong.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/users/me",
        "/api/v1/tasks",
        "/api/v1/tasks/1",
        "/api/v1/projects/1/tasks",
    ],
)
async def test_private_routes_require_credentials(
    client: AsyncClient, path: str
) -> None:
    client.headers.pop("Authorization")
    response = await client.get(path)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("authorization", ["Bearer invalid", "Basic abc", "Bearer"])
async def test_malformed_authorization_is_401(
    client: AsyncClient, authorization: str
) -> None:
    response = await client.get(
        "/api/v1/users/me", headers={"Authorization": authorization}
    )
    assert response.status_code == 401


@pytest.mark.parametrize(
    "change",
    [
        {"exp": 1},
        {"nbf": 4_000_000_000},
        {"iat": 4_000_000_000},
        {"sub": "0"},
        {"sub": "-1"},
        {"sub": "abc"},
        {"sub": "9999999999"},
        {"sub": 1},
        {"token_type": "refresh"},
        {"iss": "another-app"},
        {"aud": "another-api"},
        {"jti": "invalid"},
    ],
)
async def test_invalid_signed_claims_are_rejected(
    client: AsyncClient,
    current_user: User,
    test_settings: Settings,
    change: dict[str, Any],
) -> None:
    payload = jwt.decode(
        create_access_token(current_user.id, test_settings),
        options={"verify_signature": False},
    )
    payload.update(change)
    token = jwt.encode(payload, test_settings.signing_key(), algorithm=JWT_ALGORITHM)
    response = await client.get(
        "/api/v1/users/me", headers={"Authorization": "Bearer " + token}
    )
    assert response.status_code == 401


@pytest.mark.parametrize(
    "claim", ["exp", "sub", "iss", "aud", "iat", "nbf", "jti", "token_type"]
)
async def test_required_claims_cannot_be_omitted(
    client: AsyncClient, current_user: User, test_settings: Settings, claim: str
) -> None:
    payload = jwt.decode(
        create_access_token(current_user.id, test_settings),
        options={"verify_signature": False},
    )
    payload.pop(claim)
    token = jwt.encode(payload, test_settings.signing_key(), algorithm=JWT_ALGORITHM)
    assert (
        await client.get(
            "/api/v1/users/me", headers={"Authorization": "Bearer " + token}
        )
    ).status_code == 401


@pytest.mark.parametrize("algorithm", ["none", "HS384"])
async def test_other_algorithms_and_bad_signatures_are_rejected(
    client: AsyncClient, current_user: User, test_settings: Settings, algorithm: str
) -> None:
    payload = jwt.decode(
        create_access_token(current_user.id, test_settings),
        options={"verify_signature": False},
    )
    token = jwt.encode(
        payload,
        "" if algorithm == "none" else test_settings.signing_key(),
        algorithm=algorithm,
    )
    assert (
        await client.get(
            "/api/v1/users/me", headers={"Authorization": "Bearer " + token}
        )
    ).status_code == 401
    wrong_key = jwt.encode(payload, token_urlsafe(48), algorithm=JWT_ALGORITHM)
    assert (
        await client.get(
            "/api/v1/users/me", headers={"Authorization": "Bearer " + wrong_key}
        )
    ).status_code == 401


async def test_disabled_user_cannot_login_or_use_existing_token(
    client: AsyncClient, current_user: User, db_session: AsyncSession
) -> None:
    current_user.is_active = False
    await db_session.flush()
    assert (await client.get("/api/v1/users/me")).status_code == 401
    response = await client.post(
        "/api/v1/auth/login",
        data={"username": current_user.email, "password": "test_password_only"},
    )
    assert response.status_code == 401


async def test_deleted_user_token_is_rejected(
    client: AsyncClient, db_session: AsyncSession, test_settings: Settings
) -> None:
    user = await new_user(db_session)
    headers = bearer(user.id, test_settings)
    await db_session.delete(user)
    await db_session.flush()
    assert (await client.get("/api/v1/users/me", headers=headers)).status_code == 401


@pytest.mark.parametrize(
    "workspace_role", [WorkspaceRole.VIEWER, WorkspaceRole.EDITOR, WorkspaceRole.OWNER]
)
async def test_workspace_roles_control_read_and_write(
    client: AsyncClient,
    db_session: AsyncSession,
    project: Project,
    references: dict[str, int],
    test_settings: Settings,
    workspace_role: WorkspaceRole,
) -> None:
    created = await client.post(
        "/api/v1/tasks", json=references | {"title": "Role test"}
    )
    assert created.status_code == 201
    task_url = f"/api/v1/tasks/{created.json()['id']}"
    member = await new_user(db_session)
    db_session.add(
        WorkspaceMember(
            workspace_id=project.workspace_id, user_id=member.id, role=workspace_role
        )
    )
    await db_session.flush()
    headers = bearer(member.id, test_settings)
    assert (await client.get(task_url, headers=headers)).status_code == 200
    expected = 403 if workspace_role == WorkspaceRole.VIEWER else 200
    assert (
        await client.patch(task_url, json={"title": "Updated"}, headers=headers)
    ).status_code == expected
    expected_delete = 403 if workspace_role == WorkspaceRole.VIEWER else 204
    assert (
        await client.delete(task_url, headers=headers)
    ).status_code == expected_delete
    expected_create = 403 if workspace_role == WorkspaceRole.VIEWER else 201
    response = await client.post(
        "/api/v1/tasks", json=references | {"title": "Member task"}, headers=headers
    )
    assert response.status_code == expected_create
    if expected_create == 201:
        assert response.json()["created_by"] == member.id


async def test_cross_workspace_access_and_task_moving_are_blocked(
    client: AsyncClient, db_session: AsyncSession, references: dict[str, int]
) -> None:
    _, foreign_project, foreign_task = await other_project(db_session)
    own_response = await client.post(
        "/api/v1/tasks", json=references | {"title": "Own task"}
    )
    assert own_response.status_code == 201
    own_id = own_response.json()["id"]
    foreign_url = f"/api/v1/tasks/{foreign_task.id}"
    assert (await client.get(foreign_url)).status_code == 403
    assert (
        await client.patch(foreign_url, json={"project_id": references["project_id"]})
    ).status_code == 403
    assert (await client.delete(foreign_url)).status_code == 403
    assert (
        await client.patch(
            f"/api/v1/tasks/{own_id}", json={"project_id": foreign_project.id}
        )
    ).status_code == 403
    assert (
        await client.post(
            "/api/v1/tasks",
            json={"project_id": foreign_project.id, "title": "Forbidden"},
        )
    ).status_code == 403
    page = (await client.get("/api/v1/tasks")).json()
    assert [item["id"] for item in page["items"]] == [own_id]
    assert page["total"] == 1


async def test_admin_uses_database_role_and_token_role_cannot_escalate(
    client: AsyncClient,
    db_session: AsyncSession,
    project: Project,
    test_settings: Settings,
) -> None:
    admin = await new_user(db_session, UserRole.ADMIN)
    outsider = await new_user(db_session)
    assert (
        await client.get(
            f"/api/v1/projects/{project.id}/tasks",
            headers=bearer(admin.id, test_settings),
        )
    ).status_code == 200
    payload = jwt.decode(
        create_access_token(outsider.id, test_settings),
        options={"verify_signature": False},
    )
    payload["role"] = "ADMIN"
    token = jwt.encode(payload, test_settings.signing_key(), algorithm=JWT_ALGORITHM)
    assert (
        await client.get(
            f"/api/v1/projects/{project.id}/tasks",
            headers={"Authorization": "Bearer " + token},
        )
    ).status_code == 403


async def test_creator_cannot_be_supplied_and_assignee_must_belong_to_workspace(
    client: AsyncClient,
    references: dict[str, int],
    current_user: User,
    db_session: AsyncSession,
) -> None:
    outsider = await new_user(db_session)
    assert (
        await client.post(
            "/api/v1/tasks",
            json=references | {"title": "Spoof", "created_by": current_user.id},
        )
    ).status_code == 422
    assert (
        await client.post(
            "/api/v1/tasks",
            json=references | {"title": "Wrong assignee", "assignee_id": outsider.id},
        )
    ).status_code == 422


async def test_swagger_documents_oauth2_and_user_response_hides_password(
    client: AsyncClient,
) -> None:
    document = (await client.get("/openapi.json")).json()
    flow = document["components"]["securitySchemes"]["OAuth2PasswordBearer"]["flows"][
        "password"
    ]
    assert flow["tokenUrl"] == "/api/v1/auth/login"
    for path in ["/api/v1/tasks", "/api/v1/users/me"]:
        assert document["paths"][path]["get"]["security"] == [
            {"OAuth2PasswordBearer": []}
        ]
    assert not document["paths"]["/api/v1/auth/register"]["post"].get("security")
    fields = document["components"]["schemas"]["UserResponse"]["properties"]
    assert "password" not in fields and "hashed_password" not in fields


def test_weak_signing_key_is_rejected_without_echoing_it(
    test_settings: Settings,
) -> None:
    weak = "weak-key-value"
    with pytest.raises(ValidationError) as exc:
        Settings.model_validate(
            test_settings.model_dump() | {"jwt_secret": SecretStr(weak)}
        )
    assert weak not in str(exc.value)


async def test_missing_signing_key_fails_at_startup(test_settings: Settings) -> None:
    settings = Settings.model_validate(
        test_settings.model_dump() | {"jwt_secret": None}
    )
    app = create_app(settings)
    with pytest.raises(ValueError, match="JWT_SECRET"):
        async with app.router.lifespan_context(app):
            pytest.fail("Startup must fail before serving requests")
