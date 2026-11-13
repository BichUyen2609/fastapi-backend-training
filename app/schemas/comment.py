from typing import Annotated

from pydantic import AwareDatetime, Field

from app.core.constants import COMMENT_MAX_LENGTH
from app.schemas.base import BaseSchema, ResourceId


class CommentCreate(BaseSchema):
    content: Annotated[str, Field(min_length=1, max_length=COMMENT_MAX_LENGTH)]


class CommentResponse(BaseSchema):
    id: ResourceId
    task_id: ResourceId
    author_id: ResourceId
    content: str
    created_at: AwareDatetime


class CommentPage(BaseSchema):
    items: list[CommentResponse]
    total: int
    page: int
    limit: int
