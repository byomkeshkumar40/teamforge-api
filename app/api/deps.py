import uuid
from typing import Annotated

from fastapi import Depends, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AuthenticationError, NotFoundError
from app.core.permissions import TenantContext
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import Membership, User
from app.schemas.common import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, PageParams

# auto_error=False so a missing header produces OUR 401 error envelope.
bearer_scheme = HTTPBearer(auto_error=False, description="JWT access token from POST /auth/login")

DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: DbSession,
) -> User:
    """Authentication: who is calling? Authorization happens later, per organization."""
    if credentials is None:
        raise AuthenticationError("Authentication required")
    user = db.get(User, decode_access_token(credentials.credentials))
    if user is None:
        raise AuthenticationError("Invalid authentication token")
    if not user.is_active:
        raise AuthenticationError("This account is disabled")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_tenant_context(org_id: uuid.UUID, user: CurrentUser, db: DbSession) -> TenantContext:
    """Tenant gate for every /organizations/{org_id}/... route.

    Non-members get 404 (not 403) so the API never confirms whether an organization
    they don't belong to exists.
    """
    role = db.scalar(
        select(Membership.role).where(
            Membership.organization_id == org_id, Membership.user_id == user.id
        )
    )
    if role is None:
        raise NotFoundError("Organization not found")
    return TenantContext(user=user, organization_id=org_id, role=role)


Tenant = Annotated[TenantContext, Depends(get_tenant_context)]


def get_page_params(
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> PageParams:
    return PageParams(limit=limit, offset=offset)


Pagination = Annotated[PageParams, Depends(get_page_params)]
