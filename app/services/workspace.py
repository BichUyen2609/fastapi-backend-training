from app.core.constants import (
    ALREADY_MEMBER,
    MEMBER_NOT_FOUND,
    OWNER_MEMBERSHIP_LOCKED,
    USER_NOT_FOUND,
    WORKSPACE_NOT_FOUND,
)
from app.core.enums import UserRole, WorkspaceRole
from app.core.exceptions import (
    ConflictException,
    InvalidReferenceException,
    NotFoundException,
)
from app.models.entities import User, Workspace
from app.repositories.access import WorkspaceAccess
from app.repositories.auth import UserRepository
from app.repositories.workspace import MemberRow, WorkspaceRepository
from app.schemas.workspace import (
    MemberCreate,
    MemberResponse,
    MemberUpdate,
    WorkspaceCreate,
    WorkspacePage,
    WorkspaceResponse,
    WorkspaceUpdate,
)
from app.services.base import ensure_role, transaction


class WorkspaceService:
    def __init__(
        self, repository: WorkspaceRepository, users: UserRepository, actor: User
    ) -> None:
        self.repository = repository
        self.users = users
        self.actor = actor

    async def authorize(
        self, workspace_id: int, minimum: WorkspaceRole
    ) -> WorkspaceAccess:
        access = await self.repository.workspace_access(workspace_id, self.actor.id)
        if access is None:
            raise NotFoundException(WORKSPACE_NOT_FOUND)
        ensure_role(self.actor, access.role, minimum)
        return access

    async def create_workspace(self, data: WorkspaceCreate) -> Workspace:
        async with transaction(self.repository.session):
            workspace = await self.repository.create(
                data.model_dump() | {"owner_id": self.actor.id}
            )
            await self.repository.add_member(
                workspace.id, self.actor.id, WorkspaceRole.OWNER
            )
        await self.repository.session.refresh(workspace)
        return workspace

    async def list_workspaces(self, page: int, limit: int) -> WorkspacePage:
        filters = (
            ()
            if self.actor.role == UserRole.ADMIN
            else (Workspace.id.in_(self.repository.visible_workspaces(self.actor.id)),)
        )
        items, total = await self.repository.paginate(page, limit, filters)
        return WorkspacePage(
            items=[WorkspaceResponse.model_validate(item) for item in items],
            total=total,
            page=page,
            limit=limit,
        )

    async def get_workspace(self, workspace_id: int) -> Workspace:
        await self.authorize(workspace_id, WorkspaceRole.VIEWER)
        workspace = await self.repository.get(workspace_id)
        if workspace is None:
            raise NotFoundException(WORKSPACE_NOT_FOUND)
        return workspace

    async def update_workspace(
        self, workspace_id: int, data: WorkspaceUpdate
    ) -> Workspace:
        async with transaction(self.repository.session):
            await self.authorize(workspace_id, WorkspaceRole.OWNER)
            workspace = await self.repository.update(workspace_id, data.model_dump())
            if workspace is None:
                raise NotFoundException(WORKSPACE_NOT_FOUND)
        return workspace

    async def delete_workspace(self, workspace_id: int) -> None:
        async with transaction(self.repository.session):
            await self.authorize(workspace_id, WorkspaceRole.OWNER)
            if not await self.repository.delete(workspace_id):
                raise NotFoundException(WORKSPACE_NOT_FOUND)

    async def list_members(self, workspace_id: int) -> list[MemberResponse]:
        access = await self.authorize(workspace_id, WorkspaceRole.VIEWER)
        rows = await self.repository.members(workspace_id, access.owner_id)
        return [self.to_member(row) for row in rows]

    async def add_member(self, workspace_id: int, data: MemberCreate) -> MemberResponse:
        async with transaction(self.repository.session, ALREADY_MEMBER):
            access = await self.authorize(workspace_id, WorkspaceRole.OWNER)
            user = await self.users.get_by_email(str(data.email))
            if user is None or not user.is_active:
                raise InvalidReferenceException(USER_NOT_FOUND)
            existing = await self.repository.workspace_access(workspace_id, user.id)
            if existing is not None and existing.role is not None:
                raise ConflictException(ALREADY_MEMBER)
            await self.repository.add_member(workspace_id, user.id, data.role)
            row = await self.member_row(workspace_id, access.owner_id, user.id)
        return self.to_member(row)

    async def update_member(
        self, workspace_id: int, user_id: int, data: MemberUpdate
    ) -> MemberResponse:
        async with transaction(self.repository.session):
            access = await self.authorize(workspace_id, WorkspaceRole.OWNER)
            if user_id == access.owner_id:
                raise ConflictException(OWNER_MEMBERSHIP_LOCKED)
            if not await self.repository.set_member_role(
                workspace_id, user_id, data.role
            ):
                raise NotFoundException(MEMBER_NOT_FOUND)
            row = await self.member_row(workspace_id, access.owner_id, user_id)
        return self.to_member(row)

    async def remove_member(self, workspace_id: int, user_id: int) -> None:
        async with transaction(self.repository.session):
            minimum = (
                WorkspaceRole.VIEWER
                if user_id == self.actor.id
                else WorkspaceRole.OWNER
            )
            access = await self.authorize(workspace_id, minimum)
            if user_id == access.owner_id:
                raise ConflictException(OWNER_MEMBERSHIP_LOCKED)
            if not await self.repository.remove_member(workspace_id, user_id):
                raise NotFoundException(MEMBER_NOT_FOUND)
            await self.repository.unassign_tasks(workspace_id, user_id)

    async def member_row(
        self, workspace_id: int, owner_id: int, user_id: int
    ) -> MemberRow:
        rows = await self.repository.members(workspace_id, owner_id, user_id)
        if not rows:
            raise NotFoundException(MEMBER_NOT_FOUND)
        return rows[0]

    @staticmethod
    def to_member(row: MemberRow) -> MemberResponse:
        return MemberResponse.model_validate(row._asdict())
