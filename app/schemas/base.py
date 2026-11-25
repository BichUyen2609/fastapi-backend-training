from typing import Annotated, Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from app.core.constants import MAX_ENTITY_ID, NON_NULL_FIELD_MESSAGE

ResourceId = Annotated[int, Field(gt=0, le=MAX_ENTITY_ID)]


class BaseSchema(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
        from_attributes=True,
    )


ItemT = TypeVar("ItemT", bound=BaseSchema)


class Page(BaseSchema, Generic[ItemT]):
    items: list[ItemT]
    total: int
    page: int
    limit: int


class ErrorResponse(BaseSchema):
    detail: str | list[dict[str, Any]]
    code: str
    request_id: str | None


def reject_null(value: object) -> object:
    if value is None:
        raise ValueError(NON_NULL_FIELD_MESSAGE)
    return value
