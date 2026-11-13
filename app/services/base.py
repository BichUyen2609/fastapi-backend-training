from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import PROJECT_ARCHIVED, PROJECT_NOT_FOUND, RESOURCE_CONFLICT
from app.core.enums import ProjectStatus, UserRole, WorkspaceRole
from app.core.exceptions import (
    ConflictException,
    ForbiddenException,
    InvalidReferenceException,
    NotFoundException,
)
from app.models.entities import User
from app.repositories.access import AccessRepository, ProjectAccess

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
) -> ProjectAccess:
    access = await repository.project_access(project_id, actor.id)
    if access is None:
        if input_reference:
            raise InvalidReferenceException(PROJECT_NOT_FOUND)
        raise NotFoundException(PROJECT_NOT_FOUND)
    ensure_role(
        actor, access.role, WorkspaceRole.EDITOR if write else WorkspaceRole.VIEWER
    )
    if write and access.status == ProjectStatus.ARCHIVED:
        raise ConflictException(PROJECT_ARCHIVED)
    return access
