from typing import Annotated

from pydantic import AwareDatetime, Field, field_validator
from pydantic.json_schema import SkipJsonSchema

from app.core.constants import DESCRIPTION_MAX_LENGTH, NAME_MAX_LENGTH
from app.core.enums import ProjectStatus
from app.schemas.base import BaseSchema, ResourceId, reject_null

ProjectName = Annotated[str, Field(min_length=1, max_length=NAME_MAX_LENGTH)]
ProjectDescription = Annotated[str, Field(max_length=DESCRIPTION_MAX_LENGTH)]


class ProjectCreate(BaseSchema):
    name: ProjectName
    description: ProjectDescription | None = None


class ProjectUpdate(BaseSchema):
    name: ProjectName | SkipJsonSchema[None] = None
    description: ProjectDescription | None = None
    status: ProjectStatus | SkipJsonSchema[None] = None

    _reject_null = field_validator("name", "status", mode="before")(reject_null)


class ProjectResponse(BaseSchema):
    id: ResourceId
    workspace_id: ResourceId
    name: str
    description: str | None
    status: ProjectStatus
    created_at: AwareDatetime


class ProjectPage(BaseSchema):
    items: list[ProjectResponse]
    total: int
    page: int
    limit: int
