from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx2 import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import hash_token, verify_password
from app.models.entities import RefreshToken, User
from tests.test_auth import PASSWORD, bearer, new_user

pytestmark = pytest.mark.anyio


async def login(
    client: AsyncClient, email: str, password: str = PASSWORD
) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/auth/login", data={"username": email, "password": password}
    )
    assert response.status_code == 200, response.text
    return dict(response.json())


async def test_login_issues_hashed_refresh_token(
    client: AsyncClient, db_session: AsyncSession, test_settings: Settings
) -> None:
    user = await new_user(db_session)
    tokens = await login(client, user.email)
    assert (
        tokens["refresh_expires_in"] == test_settings.refresh_token_expire_days * 86_400
    )
    stored = await db_session.scalar(
        select(RefreshToken).where(RefreshToken.user_id == user.id)
    )
    assert stored is not None
    assert stored.token_hash == hash_token(tokens["refresh_token"])
    assert tokens["refresh_token"] not in stored.token_hash
    assert stored.revoked_at is None


async def test_refresh_rotates_and_reuse_revokes_family(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await new_user(db_session)
    first = await login(client, user.email)
    response = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    second = response.json()
    assert second["refresh_token"] != first["refresh_token"]
    me = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": "Bearer " + second["access_token"]},
    )
    assert me.status_code == 200 and me.json()["id"] == user.id
    reused = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}
    )
    assert reused.status_code == 401
    assert reused.headers["www-authenticate"] == "Bearer"
    assert (
        await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": second["refresh_token"]}
        )
    ).status_code == 401


async def test_logout_revokes_refresh_token_and_is_idempotent(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await new_user(db_session)
    tokens = await login(client, user.email)
    body = {"refresh_token": tokens["refresh_token"]}
    assert (await client.post("/api/v1/auth/logout", json=body)).status_code == 204
    assert (await client.post("/api/v1/auth/logout", json=body)).status_code == 204
    assert (await client.post("/api/v1/auth/refresh", json=body)).status_code == 401
    assert (
        await client.post("/api/v1/auth/logout", json={"refresh_token": "unknown"})
    ).status_code == 204


async def test_expired_unknown_and_inactive_refresh_tokens_are_rejected(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await new_user(db_session)
    tokens = await login(client, user.email)
    stored = await db_session.scalar(
        select(RefreshToken).where(RefreshToken.user_id == user.id)
    )
    assert stored is not None
    stored.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.flush()
    body = {"refresh_token": tokens["refresh_token"]}
    assert (await client.post("/api/v1/auth/refresh", json=body)).status_code == 401
    assert (
        await client.post("/api/v1/auth/refresh", json={"refresh_token": "forged"})
    ).status_code == 401
    fresh = await login(client, user.email)
    user.is_active = False
    await db_session.flush()
    assert (
        await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": fresh["refresh_token"]}
        )
    ).status_code == 401


async def test_refresh_validation_does_not_echo_token(client: AsyncClient) -> None:
    token = "x" * 300
    response = await client.post("/api/v1/auth/refresh", json={"refresh_token": token})
    assert response.status_code == 422
    assert token not in response.text


async def test_update_profile_normalizes_email_and_rejects_duplicates(
    client: AsyncClient, db_session: AsyncSession, current_user: User
) -> None:
    other = await new_user(db_session)
    response = await client.patch(
        "/api/v1/users/me",
        json={"full_name": "  Renamed  ", "email": "  NEW.Mail@Example.com "},
    )
    assert response.status_code == 200
    assert response.json()["full_name"] == "Renamed"
    assert response.json()["email"] == "new.mail@example.com"
    assert (await client.patch("/api/v1/users/me", json={})).status_code == 200
    duplicate = await client.patch(
        "/api/v1/users/me", json={"email": other.email.upper()}
    )
    assert duplicate.status_code == 409
    assert duplicate.json() == {"detail": "Email already registered"}


@pytest.mark.parametrize(
    "payload",
    [
        {"full_name": None},
        {"email": None},
        {"full_name": "   "},
        {"role": "ADMIN"},
        {"is_active": False},
        {"hashed_password": "x"},
    ],
)
async def test_update_profile_rejects_invalid_or_privileged_fields(
    client: AsyncClient, payload: dict[str, object]
) -> None:
    assert (await client.patch("/api/v1/users/me", json=payload)).status_code == 422


async def test_change_password_rehashes_and_revokes_sessions(
    client: AsyncClient, db_session: AsyncSession, test_settings: Settings
) -> None:
    user = await new_user(db_session)
    tokens = await login(client, user.email)
    headers = bearer(user.id, test_settings)
    wrong = await client.post(
        "/api/v1/users/me/password",
        json={"current_password": "Wrong_password", "new_password": "Another_pw_1"},
        headers=headers,
    )
    assert wrong.status_code == 400
    assert wrong.json() == {"detail": "Current password is incorrect"}
    same = await client.post(
        "/api/v1/users/me/password",
        json={"current_password": PASSWORD, "new_password": PASSWORD},
        headers=headers,
    )
    assert same.status_code == 400
    short = await client.post(
        "/api/v1/users/me/password",
        json={"current_password": PASSWORD, "new_password": "Tiny7"},
        headers=headers,
    )
    assert short.status_code == 422 and "Tiny7" not in short.text
    response = await client.post(
        "/api/v1/users/me/password",
        json={"current_password": PASSWORD, "new_password": "Brand_new_pw_2"},
        headers=headers,
    )
    assert response.status_code == 204
    await db_session.refresh(user)
    assert verify_password("Brand_new_pw_2", user.hashed_password)
    assert (
        await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
    ).status_code == 401
    assert (
        await client.post(
            "/api/v1/auth/login", data={"username": user.email, "password": PASSWORD}
        )
    ).status_code == 401
    await login(client, user.email, "Brand_new_pw_2")
