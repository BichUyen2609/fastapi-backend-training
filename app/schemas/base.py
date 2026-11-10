from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.constants import MAX_ENTITY_ID

ResourceId = Annotated[int, Field(gt=0, le=MAX_ENTITY_ID)]


class BaseSchema(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
        from_attributes=True,
    )


class ErrorResponse(BaseSchema):
    detail: str | list[dict[str, Any]]
