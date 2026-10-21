import logging
import re
import secrets

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.core.permissions import Permission, TenantContext, authorize
from app.models import Membership, Organization, Role, User
from app.schemas.common import PageParams
from app.schemas.organization import OrganizationCreate, OrganizationUpdate

logger = logging.getLogger(__name__)


def _make_slug(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "org"
    return f"{base}-{secrets.token_hex(3)}"  # random suffix keeps slugs unique


def create_organization(
    db: Session, user: User, data: OrganizationCreate
) -> tuple[Organization, Role]:
    """Create the organization and its first OWNER membership in ONE transaction."""
    org = Organization(name=data.name, slug=_make_slug(data.name), created_by=user.id)
    db.add(org)
    db.flush()  # assigns org.id without committing
    db.add(Membership(organization_id=org.id, user_id=user.id, role=Role.OWNER))
    db.commit()
    logger.info(
        "organization_created", extra={"organization_id": str(org.id), "actor_id": str(user.id)}
    )
    return org, Role.OWNER


def list_user_organizations(
    db: Session, user: User, page: PageParams
) -> tuple[list[tuple[Organization, Role]], int]:
    """Only organizations the user is a member of: the join on memberships IS the filter."""
    base = (
        select(Organization, Membership.role)
        .join(Membership, Membership.organization_id == Organization.id)
        .where(Membership.user_id == user.id)
    )
    total = db.scalar(
        select(func.count()).select_from(Membership).where(Membership.user_id == user.id)
    )
    rows = db.execute(
        base.order_by(Organization.created_at.desc(), Organization.id)
        .limit(page.limit)
        .offset(page.offset)
    ).all()
    return [(org, role) for org, role in rows], total or 0


def get_organization(db: Session, ctx: TenantContext) -> Organization:
    org = db.get(Organization, ctx.organization_id)
    if org is None:
        raise NotFoundError("Organization not found")
    return org


def update_organization(db: Session, ctx: TenantContext, data: OrganizationUpdate) -> Organization:
    authorize(ctx, Permission.ORG_UPDATE)
    org = get_organization(db, ctx)
    org.name = data.name
    db.commit()
    return org


def delete_organization(db: Session, ctx: TenantContext) -> None:
    """Owner only. Foreign keys cascade to memberships, invitations, projects and tasks."""
    authorize(ctx, Permission.ORG_DELETE)
    org = get_organization(db, ctx)
    db.delete(org)
    db.commit()
    logger.info(
        "organization_deleted",
        extra={"organization_id": str(ctx.organization_id), "actor_id": str(ctx.user.id)},
    )
