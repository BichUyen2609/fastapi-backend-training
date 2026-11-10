from datetime import date
from typing import Annotated

from pydantic import AwareDatetime, Field, field_validator
from pydantic.json_schema import SkipJsonSchema

from app.core.constants import (
    DESCRIPTION_MAX_LENGTH,
    NON_NULL_FIELD_MESSAGE,
    TITLE_MAX_LENGTH,
    TITLE_MIN_LENGTH,
)
from app.core.enums import TaskPriority, TaskStatus
from app.schemas.base import BaseSchema, ResourceId

TaskTitle = Annotated[
    str, Field(min_length=TITLE_MIN_LENGTH, max_length=TITLE_MAX_LENGTH)
]
TaskDescription = Annotated[str, Field(max_length=DESCRIPTION_MAX_LENGTH)]


class TaskCreate(BaseSchema):
    project_id: ResourceId
    created_by: ResourceId
    assignee_id: ResourceId | None = None
    title: TaskTitle
    description: TaskDescription | None = None
    status: TaskStatus = TaskStatus.TODO
    priority: TaskPriority = TaskPriority.MEDIUM
    due_date: date | None = None


class TaskUpdate(BaseSchema):
    project_id: ResourceId | SkipJsonSchema[None] = None
    assignee_id: ResourceId | None = None
    title: TaskTitle | SkipJsonSchema[None] = None
    status: TaskStatus | SkipJsonSchema[None] = None
    priority: TaskPriority | SkipJsonSchema[None] = None
    description: TaskDescription | None = None
    due_date: date | None = None

    @field_validator("title", "status", "priority", "project_id", mode="before")
    @classmethod
    def reject_explicit_null(cls, value: object) -> object:
        if value is None:
            raise ValueError(NON_NULL_FIELD_MESSAGE)
        return value


class TaskResponse(TaskCreate):
    id: ResourceId
    created_at: AwareDatetime
    updated_at: AwareDatetime


class TaskPage(BaseSchema):
    items: list[TaskResponse]
    total: int
    page: int
    limit: int
