import uuid

from fastapi import APIRouter, Response, status

from app.api.deps import CurrentUser, DbSession, Pagination, Tenant
from app.core.config import get_settings
from app.models import Membership, Organization, Role
from app.schemas.common import Page
from app.schemas.organization import (
    InvitationAccept,
    InvitationCreate,
    InvitationCreated,
    InvitationRead,
    MemberRead,
    OrganizationCreate,
    OrganizationUpdate,
    OrganizationWithRole,
    RoleUpdate,
)
from app.services import invitations as invitation_service
from app.services import members as member_service
from app.services import organizations as org_service

router = APIRouter(tags=["organizations"])


def _org_with_role(org: Organization, role: Role) -> OrganizationWithRole:
    return OrganizationWithRole(
        id=org.id, name=org.name, slug=org.slug, created_at=org.created_at, role=role
    )


def _member(membership: Membership) -> MemberRead:
    return MemberRead(
        user_id=membership.user_id,
        email=membership.user.email,
        full_name=membership.user.full_name,
        role=membership.role,
        joined_at=membership.created_at,
    )


# ---------------------------------------------------------------- organizations


@router.post(
    "/organizations", response_model=OrganizationWithRole, status_code=status.HTTP_201_CREATED
)
def create_organization(data: OrganizationCreate, user: CurrentUser, db: DbSession):
    org, role = org_service.create_organization(db, user, data)
    return _org_with_role(org, role)


@router.get("/organizations", response_model=Page[OrganizationWithRole])
def list_my_organizations(user: CurrentUser, db: DbSession, page: Pagination):
    rows, total = org_service.list_user_organizations(db, user, page)
    return Page(
        items=[_org_with_role(org, role) for org, role in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/organizations/{org_id}", response_model=OrganizationWithRole)
def get_organization(ctx: Tenant, db: DbSession):
    return _org_with_role(org_service.get_organization(db, ctx), ctx.role)


@router.patch("/organizations/{org_id}", response_model=OrganizationWithRole)
def update_organization(data: OrganizationUpdate, ctx: Tenant, db: DbSession):
    return _org_with_role(org_service.update_organization(db, ctx, data), ctx.role)


@router.delete("/organizations/{org_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_organization(ctx: Tenant, db: DbSession):
    org_service.delete_organization(db, ctx)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------- members


@router.get("/organizations/{org_id}/members", response_model=Page[MemberRead])
def list_members(ctx: Tenant, db: DbSession, page: Pagination):
    rows, total = member_service.list_members(db, ctx, page)
    return Page(items=[_member(m) for m in rows], total=total, limit=page.limit, offset=page.offset)


@router.patch("/organizations/{org_id}/members/{user_id}", response_model=MemberRead)
def change_member_role(user_id: uuid.UUID, data: RoleUpdate, ctx: Tenant, db: DbSession):
    return _member(member_service.change_role(db, ctx, user_id, data.role))


@router.delete("/organizations/{org_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(user_id: uuid.UUID, ctx: Tenant, db: DbSession):
    member_service.remove_member(db, ctx, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------ invitations


@router.post(
    "/organizations/{org_id}/invitations",
    response_model=InvitationCreated,
    response_model_exclude_none=True,
    status_code=status.HTTP_201_CREATED,
)
def create_invitation(data: InvitationCreate, ctx: Tenant, db: DbSession):
    invitation, raw_token = invitation_service.create_invitation(db, ctx, data)
    body = InvitationCreated.model_validate(invitation)
    if get_settings().expose_invitation_tokens:  # development/test only; blocked in production
        body.token = raw_token
    return body


@router.get("/organizations/{org_id}/invitations", response_model=Page[InvitationRead])
def list_invitations(ctx: Tenant, db: DbSession, page: Pagination):
    rows, total = invitation_service.list_pending(db, ctx, page)
    return Page(
        items=[InvitationRead.model_validate(i) for i in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.delete(
    "/organizations/{org_id}/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT
)
def revoke_invitation(invitation_id: uuid.UUID, ctx: Tenant, db: DbSession):
    invitation_service.revoke_invitation(db, ctx, invitation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/invitations/accept", response_model=OrganizationWithRole)
def accept_invitation(data: InvitationAccept, user: CurrentUser, db: DbSession):
    org, membership = invitation_service.accept_invitation(db, user, data.token)
    return _org_with_role(org, membership.role)
