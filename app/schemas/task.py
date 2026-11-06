from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from pydantic import Field, field_validator
from pydantic.json_schema import SkipJsonSchema

from app.core.constants import (
    DESCRIPTION_MAX_LENGTH,
    NON_NULL_FIELD_MESSAGE,
    TITLE_MAX_LENGTH,
    TITLE_MIN_LENGTH,
)
from app.models.task import TaskPriority, TaskStatus
from app.schemas.base import BaseSchema

TaskTitle = Annotated[
    str, Field(min_length=TITLE_MIN_LENGTH, max_length=TITLE_MAX_LENGTH)
]
TaskDescription = Annotated[str, Field(max_length=DESCRIPTION_MAX_LENGTH)]


class TaskCreate(BaseSchema):
    title: TaskTitle
    description: TaskDescription | None = None
    status: TaskStatus = TaskStatus.TODO
    priority: TaskPriority = TaskPriority.MEDIUM
    due_date: date | None = None


class TaskUpdate(BaseSchema):
    # None defaults allow omission. The validator rejects explicitly supplied nulls.
    # SkipJsonSchema keeps the OpenAPI contract aligned with accepted input.
    title: TaskTitle | SkipJsonSchema[None] = None
    status: TaskStatus | SkipJsonSchema[None] = None
    priority: TaskPriority | SkipJsonSchema[None] = None
    description: TaskDescription | None = None
    due_date: date | None = None

    @field_validator("title", "status", "priority", mode="before")
    @classmethod
    def reject_explicit_null(cls, value: object) -> object:
        if value is None:
            raise ValueError(NON_NULL_FIELD_MESSAGE)
        return value


class TaskResponse(TaskCreate):
    id: UUID
    created_at: datetime
    updated_at: datetime
