import uuid
from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.models import TaskPriority, TaskStatus
from app.schemas.common import NO_NUL

TaskTitle = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200, pattern=NO_NUL)
]
TaskDescription = Annotated[str, Field(max_length=10000, pattern=NO_NUL)]


class TaskCreate(BaseModel):
    project_id: uuid.UUID
    title: TaskTitle
    description: TaskDescription | None = None
    status: TaskStatus = TaskStatus.TODO
    priority: TaskPriority = TaskPriority.MEDIUM
    assignee_id: uuid.UUID | None = None
    due_date: date | None = None


class TaskUpdate(BaseModel):
    """Partial update. Omitted fields are untouched; description, assignee_id and due_date
    may be set to null to clear them. A task cannot be moved between projects."""

    title: TaskTitle | None = None
    description: TaskDescription | None = None
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    assignee_id: uuid.UUID | None = None
    due_date: date | None = None

    @field_validator("title", "status", "priority")
    @classmethod
    def _not_null(cls, value):
        if value is None:
            raise ValueError("this field cannot be null")
        return value


class TaskAssign(BaseModel):
    assignee_id: uuid.UUID | None = Field(description="User id of an organization member, or null")


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    project_id: uuid.UUID
    title: str
    description: str | None
    status: TaskStatus
    priority: TaskPriority
    assignee_id: uuid.UUID | None
    due_date: date | None
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
