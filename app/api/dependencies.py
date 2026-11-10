from collections.abc import AsyncIterator
from typing import Annotated, cast

from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.constants import API_V1_PREFIX
from app.core.exceptions import AuthenticationException
from app.core.security import decode_access_token
from app.database import Database
from app.models.entities import User
from app.repositories.auth import UserRepository
from app.repositories.task import TaskRepository
from app.services.auth import AuthService
from app.services.task import TaskService

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{API_V1_PREFIX}/auth/login", auto_error=False
)


def get_app_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    database = cast(Database, request.app.state.database)
    async with database.sessions() as session:
        yield session


async def get_current_user(
    token: Annotated[str | None, Depends(oauth2_scheme)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> User:
    if token is None:
        raise AuthenticationException()
    user_id = decode_access_token(token, settings)
    user = await UserRepository(session).get(user_id)
    if user is None or not user.is_active:
        raise AuthenticationException()
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_auth_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> AuthService:
    return AuthService(UserRepository(session), settings)


def get_task_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TaskRepository:
    return TaskRepository(session)


def get_task_service(
    repository: Annotated[TaskRepository, Depends(get_task_repository)],
    user: CurrentUser,
) -> TaskService:
    return TaskService(repository, user)


TaskServiceDependency = Annotated[TaskService, Depends(get_task_service)]
AuthServiceDependency = Annotated[AuthService, Depends(get_auth_service)]
