from typing import Annotated

from pydantic import AwareDatetime, Field, field_validator
from pydantic.json_schema import SkipJsonSchema

from app.core.constants import COLOR_PATTERN, NAME_MAX_LENGTH
from app.schemas.base import BaseSchema, ResourceId, reject_null

LabelName = Annotated[str, Field(min_length=1, max_length=NAME_MAX_LENGTH)]
LabelColor = Annotated[str, Field(pattern=COLOR_PATTERN, examples=["#1d76db"])]


def lowercase_color(value: str | None) -> str | None:
    return value.lower() if value is not None else value


class LabelCreate(BaseSchema):
    name: LabelName
    color: LabelColor

    _lowercase_color = field_validator("color")(lowercase_color)


class LabelUpdate(BaseSchema):
    name: LabelName | SkipJsonSchema[None] = None
    color: LabelColor | SkipJsonSchema[None] = None

    _reject_null = field_validator("name", "color", mode="before")(reject_null)
    _lowercase_color = field_validator("color")(lowercase_color)


class LabelResponse(BaseSchema):
    id: ResourceId
    project_id: ResourceId
    name: str
    color: str
    created_at: AwareDatetime
