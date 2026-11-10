from collections.abc import AsyncIterator
from pathlib import Path
from secrets import token_urlsafe
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx2 import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import Connection, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.api.dependencies import get_session
from app.core.config import Settings, get_settings
from app.core.security import create_access_token, hash_password
from app.main import create_app
from app.models.entities import Project, User, Workspace


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def test_settings() -> Settings:
    settings = get_settings()
    assert settings.test_database_url is not None, "Set TEST_DATABASE_URL"
    test_url = make_url(str(settings.test_database_url))
    assert test_url.database != make_url(str(settings.database_url)).database
    assert (test_url.database or "").endswith("_test")
    return Settings.model_validate(
        settings.model_dump()
        | {
            "database_url": settings.test_database_url,
            "jwt_secret": SecretStr(token_urlsafe(48)),
        }
    )


@pytest.fixture
async def database_engine(test_settings: Settings) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(str(test_settings.database_url), poolclass=NullPool)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def connection(database_engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    async with database_engine.connect() as connection:

        def upgrade(sync_connection: Connection) -> None:
            config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
            config.attributes["connection"] = sync_connection
            command.upgrade(config, "head")

        await connection.run_sync(upgrade)
        await connection.commit()
        transaction = await connection.begin()
        try:
            yield connection
        finally:
            await transaction.rollback()


@pytest.fixture
async def db_session(connection: AsyncConnection) -> AsyncIterator[AsyncSession]:
    async with AsyncSession(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    ) as session:
        yield session


@pytest.fixture
async def project(db_session: AsyncSession) -> Project:
    user = User(
        email=f"{uuid4().hex}@example.test",
        full_name="Owner",
        hashed_password=hash_password("test_password_only"),
    )
    db_session.add(user)
    await db_session.flush()
    workspace = Workspace(name="Test workspace", owner_id=user.id)
    db_session.add(workspace)
    await db_session.flush()
    project = Project(name="Test project", workspace_id=workspace.id)
    db_session.add(project)
    await db_session.flush()
    return project


@pytest.fixture
async def current_user(project: Project, db_session: AsyncSession) -> User:
    owner_id = await db_session.scalar(
        select(Workspace.owner_id).where(Workspace.id == project.workspace_id)
    )
    assert owner_id is not None
    user = await db_session.get(User, owner_id)
    assert user is not None
    return user


@pytest.fixture
def references(project: Project) -> dict[str, int]:
    return {"project_id": project.id}


@pytest.fixture
def application(test_settings: Settings) -> FastAPI:
    return create_app(test_settings)


@pytest.fixture
async def client(
    application: FastAPI,
    connection: AsyncConnection,
    current_user: User,
    test_settings: Settings,
) -> AsyncIterator[AsyncClient]:
    async def override_session() -> AsyncIterator[AsyncSession]:
        async with AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        ) as session:
            yield session

    application.dependency_overrides[get_session] = override_session
    try:
        async with (
            application.router.lifespan_context(application),
            AsyncClient(
                transport=ASGITransport(app=application),
                base_url="http://testserver",
                headers={
                    "Authorization": "Bearer "
                    + create_access_token(current_user.id, test_settings)
                },
            ) as test_client,
        ):
            yield test_client
    finally:
        application.dependency_overrides.clear()
