from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import TypedDict
from uuid import UUID


class TaskStatus(StrEnum):
    TODO = "TODO"
    IN_PROGRESS = "IN_PROGRESS"
    IN_REVIEW = "IN_REVIEW"
    DONE = "DONE"


class TaskPriority(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    URGENT = "URGENT"


@dataclass(frozen=True, slots=True)
class Task:
    id: UUID
    title: str
    description: str | None
    status: TaskStatus
    priority: TaskPriority
    due_date: date | None
    created_at: datetime
    updated_at: datetime


class TaskChanges(TypedDict, total=False):
    """Only supplied fields are updated; None explicitly clears nullable fields."""

    title: str
    description: str | None
    status: TaskStatus
    priority: TaskPriority
    due_date: date | None
