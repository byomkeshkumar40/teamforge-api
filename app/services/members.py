import logging
import uuid
from dataclasses import replace

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError
from app.core.permissions import Permission, TenantContext, authorize
from app.models import Membership, Organization, Role, Task
from app.schemas.common import PageParams

logger = logging.getLogger(__name__)

LAST_OWNER = "An organization must keep at least one owner"


def list_members(db: Session, ctx: TenantContext, page: PageParams) -> tuple[list[Membership], int]:
    where = Membership.organization_id == ctx.organization_id
    total = db.scalar(select(func.count()).select_from(Membership).where(where)) or 0
    rows = db.scalars(
        select(Membership)
        .where(where)
        .order_by(Membership.created_at, Membership.id)
        .limit(page.limit)
        .offset(page.offset)
    ).all()
    return list(rows), total


def _lock_organization_and_refresh_actor(db: Session, ctx: TenantContext) -> TenantContext:
    """Serialise ownership-affecting changes within one organization.

    `SELECT ... FOR UPDATE` on the organization row makes concurrent role changes and
    removals for the SAME organization run one after another (other organizations are
    unaffected). Once we hold the lock we re-read the caller's role: it may have been
    changed by the request we just waited for, and the role loaded earlier by the
    dependency would be stale. This is what makes the last-owner rule safe under
    concurrency: the "count owners" check and the write happen under the same lock.
    """
    locked = db.scalar(
        select(Organization.id).where(Organization.id == ctx.organization_id).with_for_update()
    )
    if locked is None:
        raise NotFoundError("Organization not found")
    role = db.scalar(
        select(Membership.role).where(
            Membership.organization_id == ctx.organization_id, Membership.user_id == ctx.user.id
        )
    )
    if role is None:  # the caller was removed while this request was waiting
        raise NotFoundError("Organization not found")
    return replace(ctx, role=role)


def _owner_count(db: Session, organization_id: uuid.UUID) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(Membership)
            .where(Membership.organization_id == organization_id, Membership.role == Role.OWNER)
        )
        or 0
    )


def _get_membership(db: Session, organization_id: uuid.UUID, user_id: uuid.UUID) -> Membership:
    membership = db.scalar(
        select(Membership)
        .where(Membership.organization_id == organization_id, Membership.user_id == user_id)
        .execution_options(populate_existing=True)
    )
    if membership is None:
        raise NotFoundError("Member not found")
    return membership


def change_role(
    db: Session, ctx: TenantContext, target_user_id: uuid.UUID, new_role: Role
) -> Membership:
    ctx = _lock_organization_and_refresh_actor(db, ctx)
    authorize(ctx, Permission.MEMBERS_MANAGE)
    target = _get_membership(db, ctx.organization_id, target_user_id)

    if target.role == new_role:
        return target
    # Only owners may grant or revoke ownership.
    if ctx.role != Role.OWNER and Role.OWNER in (target.role, new_role):
        raise PermissionDeniedError("Only an owner can grant or revoke ownership")
    if target.role == Role.OWNER and _owner_count(db, ctx.organization_id) <= 1:
        raise ConflictError(LAST_OWNER)

    target.role = new_role
    db.commit()
    logger.info(
        "member_role_changed",
        extra={
            "organization_id": str(ctx.organization_id),
            "actor_id": str(ctx.user.id),
            "target_user_id": str(target_user_id),
            "new_role": new_role.value,
        },
    )
    return target


def remove_member(db: Session, ctx: TenantContext, target_user_id: uuid.UUID) -> None:
    """Remove a member, or let a member leave (target == caller)."""
    ctx = _lock_organization_and_refresh_actor(db, ctx)
    is_self = target_user_id == ctx.user.id
    if not is_self:
        authorize(ctx, Permission.MEMBERS_MANAGE)
    target = _get_membership(db, ctx.organization_id, target_user_id)

    if not is_self and target.role == Role.OWNER and ctx.role != Role.OWNER:
        raise PermissionDeniedError("Only an owner can remove an owner")
    if target.role == Role.OWNER and _owner_count(db, ctx.organization_id) <= 1:
        raise ConflictError(LAST_OWNER)

    # The tasks -> memberships composite FK forbids deleting a membership that still has
    # assigned tasks, so unassign them first, in the same transaction.
    db.execute(
        update(Task)
        .where(Task.organization_id == ctx.organization_id, Task.assignee_id == target_user_id)
        .values(assignee_id=None)
    )
    db.delete(target)
    db.commit()
    logger.info(
        "member_removed",
        extra={
            "organization_id": str(ctx.organization_id),
            "actor_id": str(ctx.user.id),
            "target_user_id": str(target_user_id),
        },
    )
