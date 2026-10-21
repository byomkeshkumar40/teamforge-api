import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.schemas.common import NO_NUL

ProjectName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100, pattern=NO_NUL)
]
Description = Annotated[str, Field(max_length=5000, pattern=NO_NUL)]


class ProjectCreate(BaseModel):
    name: ProjectName
    description: Description | None = None


class ProjectUpdate(BaseModel):
    name: ProjectName | None = None
    description: Description | None = None

    @field_validator("name")
    @classmethod
    def _name_not_null(cls, value: str | None) -> str:
        # Runs only when "name" is supplied, so an explicit null is rejected.
        if value is None:
            raise ValueError("name cannot be null")
        return value


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    description: str | None
    archived_at: datetime | None
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
