from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.errors import AuthenticationError
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import User

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
