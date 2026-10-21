import hashlib
import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import BadRequestError, ConflictError, NotFoundError
from app.core.permissions import Permission, TenantContext, authorize
from app.models import Invitation, Membership, Organization, User
from app.schemas.common import PageParams
from app.schemas.organization import InvitationCreate

logger = logging.getLogger(__name__)

INVALID_INVITATION = "Invalid or expired invitation"


def hash_token(token: str) -> str:
    """SHA-256 is appropriate here: tokens are 256-bit random values, not human passwords."""
    return hashlib.sha256(token.encode()).hexdigest()


def create_invitation(
    db: Session, ctx: TenantContext, data: InvitationCreate
) -> tuple[Invitation, str]:
    """Returns the invitation and the RAW token. The raw token is never stored or logged."""
    authorize(ctx, Permission.INVITATIONS_MANAGE)

    already_member = db.scalar(
        select(Membership.id)
        .join(User, User.id == Membership.user_id)
        .where(Membership.organization_id == ctx.organization_id, User.email == data.email)
    )
    if already_member:
        raise ConflictError("This user is already a member of the organization")

    # Re-inviting replaces the previous pending invitation (invalidating its token).
    db.execute(
        delete(Invitation).where(
            Invitation.organization_id == ctx.organization_id,
            Invitation.email == data.email,
            Invitation.accepted_at.is_(None),
        )
    )
    raw_token = secrets.token_urlsafe(32)
    invitation = Invitation(
        organization_id=ctx.organization_id,
        email=data.email,
        role=data.role,
        token_hash=hash_token(raw_token),
        expires_at=datetime.now(UTC) + timedelta(hours=get_settings().invitation_expire_hours),
        invited_by=ctx.user.id,
    )
    db.add(invitation)
    try:
        db.commit()
    except IntegrityError:  # two simultaneous invites for the same email
        db.rollback()
        raise ConflictError("An invitation for this email is already being created") from None
    logger.info(
        "invitation_created",
        extra={"organization_id": str(ctx.organization_id), "invitation_id": str(invitation.id)},
    )
    return invitation, raw_token


def list_pending(db: Session, ctx: TenantContext, page: PageParams) -> tuple[list[Invitation], int]:
    authorize(ctx, Permission.INVITATIONS_MANAGE)
    where = (
        Invitation.organization_id == ctx.organization_id,
        Invitation.accepted_at.is_(None),
    )
    total = db.scalar(select(func.count()).select_from(Invitation).where(*where)) or 0
    rows = db.scalars(
        select(Invitation)
        .where(*where)
        .order_by(Invitation.created_at.desc(), Invitation.id)
        .limit(page.limit)
        .offset(page.offset)
    ).all()
    return list(rows), total


def revoke_invitation(db: Session, ctx: TenantContext, invitation_id: uuid.UUID) -> None:
    authorize(ctx, Permission.INVITATIONS_MANAGE)
    invitation = db.scalar(
        select(Invitation).where(
            Invitation.id == invitation_id,
            Invitation.organization_id == ctx.organization_id,  # tenant scope
            Invitation.accepted_at.is_(None),
        )
    )
    if invitation is None:
        raise NotFoundError("Invitation not found")
    db.delete(invitation)
    db.commit()


def accept_invitation(db: Session, user: User, token: str) -> tuple[Organization, Membership]:
    """Any failure returns the same generic error so tokens cannot be probed."""
    invitation = db.scalar(
        select(Invitation)
        .where(Invitation.token_hash == hash_token(token))
        .with_for_update()  # serialises two simultaneous accepts of the same token
    )
    if (
        invitation is None
        or invitation.accepted_at is not None
        or invitation.expires_at <= datetime.now(UTC)
        # the invitation was sent to an email address; only that account may redeem it
        or invitation.email != user.email
    ):
        db.rollback()
        raise BadRequestError(INVALID_INVITATION)

    already_member = db.scalar(
        select(Membership.id).where(
            Membership.organization_id == invitation.organization_id,
            Membership.user_id == user.id,
        )
    )
    if already_member:
        db.rollback()
        raise ConflictError("You are already a member of this organization")

    membership = Membership(
        organization_id=invitation.organization_id, user_id=user.id, role=invitation.role
    )
    invitation.accepted_at = datetime.now(UTC)
    db.add(membership)
    db.commit()
    organization = db.get(Organization, invitation.organization_id)
    logger.info(
        "invitation_accepted",
        extra={"organization_id": str(invitation.organization_id), "actor_id": str(user.id)},
    )
    return organization, membership
