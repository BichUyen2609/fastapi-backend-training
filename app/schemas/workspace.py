from typing import Annotated

from pydantic import AwareDatetime, EmailStr, Field, field_validator

from app.core.constants import (
    EMAIL_MAX_LENGTH,
    NAME_MAX_LENGTH,
    OWNER_ROLE_NOT_ASSIGNABLE,
)
from app.core.enums import WorkspaceRole
from app.schemas.base import BaseSchema, ResourceId

WorkspaceName = Annotated[str, Field(min_length=1, max_length=NAME_MAX_LENGTH)]


def reject_owner_role(value: WorkspaceRole) -> WorkspaceRole:
    if value == WorkspaceRole.OWNER:
        raise ValueError(OWNER_ROLE_NOT_ASSIGNABLE)
    return value


class WorkspaceCreate(BaseSchema):
    name: WorkspaceName


class WorkspaceUpdate(BaseSchema):
    name: WorkspaceName


class WorkspaceResponse(BaseSchema):
    id: ResourceId
    name: str
    owner_id: ResourceId
    created_at: AwareDatetime


class WorkspacePage(BaseSchema):
    items: list[WorkspaceResponse]
    total: int
    page: int
    limit: int


class MemberCreate(BaseSchema):
    email: Annotated[EmailStr, Field(max_length=EMAIL_MAX_LENGTH)]
    role: WorkspaceRole = WorkspaceRole.VIEWER

    _reject_owner = field_validator("role")(reject_owner_role)


class MemberUpdate(BaseSchema):
    role: WorkspaceRole

    _reject_owner = field_validator("role")(reject_owner_role)


class MemberResponse(BaseSchema):
    user_id: ResourceId
    email: str
    full_name: str
    role: WorkspaceRole
