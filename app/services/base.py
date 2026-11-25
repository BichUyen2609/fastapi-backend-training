from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import (
    PROJECT_ARCHIVED,
    PROJECT_NOT_FOUND,
    RESOURCE_CONFLICT,
    TASK_NOT_FOUND,
    WORKSPACE_NOT_FOUND,
)
from app.core.enums import ProjectStatus, UserRole, WorkspaceRole
from app.core.exceptions import (
    ConflictException,
    ForbiddenException,
    InvalidReferenceException,
    NotFoundException,
)
from app.models.entities import User
from app.repositories.access import AccessRepository, ProjectAccess, WorkspaceAccess

ROLE_RANK: dict[WorkspaceRole, int] = {
    WorkspaceRole.VIEWER: 1,
    WorkspaceRole.EDITOR: 2,
    WorkspaceRole.OWNER: 3,
}


@asynccontextmanager
async def transaction(
    session: AsyncSession, conflict_message: str = RESOURCE_CONFLICT
) -> AsyncIterator[None]:
    try:
        yield
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ConflictException(conflict_message) from exc
    except BaseException:
        await session.rollback()
        raise


def has_role(actor: User, role: WorkspaceRole | None, minimum: WorkspaceRole) -> bool:
    if actor.role == UserRole.ADMIN:
        return True
    return role is not None and ROLE_RANK[role] >= ROLE_RANK[minimum]


def ensure_role(
    actor: User, role: WorkspaceRole | None, minimum: WorkspaceRole
) -> None:
    if not has_role(actor, role, minimum):
        raise ForbiddenException()


async def authorize_project(
    repository: AccessRepository,
    actor: User,
    project_id: int,
    *,
    write: bool = False,
    input_reference: bool = False,
    minimum: WorkspaceRole | None = None,
) -> ProjectAccess:
    access = await repository.project_access(project_id, actor.id)
    if access is None:
        if input_reference:
            raise InvalidReferenceException(PROJECT_NOT_FOUND)
        raise NotFoundException(PROJECT_NOT_FOUND)
    required_role = (
        minimum
        if minimum is not None
        else (WorkspaceRole.EDITOR if write else WorkspaceRole.VIEWER)
    )
    ensure_role(actor, access.role, required_role)
    if write and access.status == ProjectStatus.ARCHIVED:
        raise ConflictException(PROJECT_ARCHIVED)
    return access


async def authorize_workspace(
    repository: AccessRepository,
    actor: User,
    workspace_id: int,
    minimum: WorkspaceRole = WorkspaceRole.VIEWER,
) -> WorkspaceAccess:
    access = await repository.workspace_access(workspace_id, actor.id)
    if access is None:
        raise NotFoundException(WORKSPACE_NOT_FOUND)
    ensure_role(actor, access.role, minimum)
    return access


async def require_task_project(repository: AccessRepository, task_id: int) -> int:
    project_id = await repository.task_project(task_id)
    if project_id is None:
        raise NotFoundException(TASK_NOT_FOUND)
    return project_id
