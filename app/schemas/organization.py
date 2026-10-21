import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, field_validator
from pydantic.types import StringConstraints

from app.models import Role
from app.schemas.user import LowerEmail

OrgName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class OrganizationCreate(BaseModel):
    name: OrgName


class OrganizationUpdate(BaseModel):
    name: OrgName


class OrganizationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    created_at: datetime


class OrganizationWithRole(OrganizationRead):
    """An organization as seen by one member: includes that member's role."""

    role: Role


class MemberRead(BaseModel):
    user_id: uuid.UUID
    email: str
    full_name: str
    role: Role
    joined_at: datetime


class RoleUpdate(BaseModel):
    role: Role


class InvitationCreate(BaseModel):
    email: LowerEmail
    role: Role = Role.MEMBER

    @field_validator("role")
    @classmethod
    def _not_owner(cls, role: Role) -> Role:
        if role == Role.OWNER:
            raise ValueError(
                "Invitations can grant ADMIN or MEMBER; owners are promoted explicitly"
            )
        return role


class InvitationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    role: Role
    expires_at: datetime
    created_at: datetime


class InvitationCreated(InvitationRead):
    # Present only when EXPOSE_INVITATION_TOKENS=true (never allowed in production).
    token: str | None = None


class InvitationAccept(BaseModel):
    token: Annotated[str, StringConstraints(min_length=20, max_length=200)]
