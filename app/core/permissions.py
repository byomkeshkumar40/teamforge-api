"""Role-based access control.

Roles map to named permissions. Services call `authorize(ctx, Permission.X)` at the start
of every tenant-scoped write, so authorization lives at the service boundary and does not
depend on the router (or on database constraints) to have done the right thing.
Reading tenant data requires membership only, which `get_tenant_context` already proves.
"""

import uuid
from dataclasses import dataclass
from enum import StrEnum

from app.core.errors import PermissionDeniedError
from app.models import Role, User


class Permission(StrEnum):
    ORG_UPDATE = "org:update"
    ORG_DELETE = "org:delete"
    MEMBERS_MANAGE = "members:manage"
    INVITATIONS_MANAGE = "invitations:manage"
    PROJECTS_WRITE = "projects:write"
    TASKS_WRITE = "tasks:write"
    TASKS_DELETE_ANY = "tasks:delete_any"


_ADMIN_PERMISSIONS = frozenset(Permission) - {Permission.ORG_DELETE}

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.OWNER: frozenset(Permission),
    Role.ADMIN: _ADMIN_PERMISSIONS,
    Role.MEMBER: frozenset({Permission.TASKS_WRITE}),
}


@dataclass(frozen=True)
class TenantContext:
    """Who is calling, and in which organization, with which role.

    Built only by `get_tenant_context`, which proves the caller is a member of the
    organization. Every tenant-scoped query must filter on `organization_id`.
    """

    user: User
    organization_id: uuid.UUID
    role: Role

    def can(self, permission: Permission) -> bool:
        return permission in ROLE_PERMISSIONS[self.role]


def authorize(ctx: TenantContext, permission: Permission) -> None:
    if not ctx.can(permission):
        raise PermissionDeniedError("You do not have permission to perform this action")
