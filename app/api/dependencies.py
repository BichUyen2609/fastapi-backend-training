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
from app.repositories.auth import RefreshTokenRepository, UserRepository
from app.repositories.project import ProjectRepository
from app.repositories.task import TaskRepository
from app.repositories.workspace import WorkspaceRepository
from app.services.auth import AuthService
from app.services.project import ProjectService
from app.services.task import TaskService
from app.services.user import UserService
from app.services.workspace import WorkspaceService

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{API_V1_PREFIX}/auth/login", auto_error=False
)


def get_app_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    database = cast(Database, request.app.state.database)
    async with database.sessions() as session:
        yield session


SessionDependency = Annotated[AsyncSession, Depends(get_session)]


async def get_current_user(
    token: Annotated[str | None, Depends(oauth2_scheme)],
    session: SessionDependency,
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
    session: SessionDependency,
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> AuthService:
    return AuthService(
        UserRepository(session), RefreshTokenRepository(session), settings
    )


def get_user_service(session: SessionDependency, user: CurrentUser) -> UserService:
    return UserService(UserRepository(session), RefreshTokenRepository(session), user)


def get_task_repository(session: SessionDependency) -> TaskRepository:
    return TaskRepository(session)


def get_task_service(
    repository: Annotated[TaskRepository, Depends(get_task_repository)],
    user: CurrentUser,
) -> TaskService:
    return TaskService(repository, user)


def get_workspace_service(
    session: SessionDependency, user: CurrentUser
) -> WorkspaceService:
    return WorkspaceService(WorkspaceRepository(session), UserRepository(session), user)


def get_project_service(
    session: SessionDependency, user: CurrentUser
) -> ProjectService:
    return ProjectService(ProjectRepository(session), user)


TaskServiceDependency = Annotated[TaskService, Depends(get_task_service)]
AuthServiceDependency = Annotated[AuthService, Depends(get_auth_service)]
UserServiceDependency = Annotated[UserService, Depends(get_user_service)]
WorkspaceServiceDependency = Annotated[WorkspaceService, Depends(get_workspace_service)]
ProjectServiceDependency = Annotated[ProjectService, Depends(get_project_service)]
