import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

from app.core.config import get_settings
from app.core.errors import AuthenticationError

# Argon2id with the library's current recommended parameters.
_password_hash = PasswordHash((Argon2Hasher(),))


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return _password_hash.verify(password, hashed)


@lru_cache
def dummy_hash() -> str:
    """A valid hash of a throwaway password.

    Verified against when the email is unknown so that "no such user" costs the
    same as "wrong password" (reduces user-enumeration via response timing).
    """
    return hash_password("not-a-real-password")


def create_access_token(user_id: uuid.UUID, expires_delta: timedelta | None = None) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    expires = expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": str(user_id), "iat": now, "exp": now + expires}
    return jwt.encode(
        payload, settings.jwt_secret_key.get_secret_value(), algorithm=settings.jwt_algorithm
    )


def decode_access_token(token: str) -> uuid.UUID:
    """Validate signature, expiry and required claims; return the user id.

    The accepted algorithm list is fixed server-side, so tokens using "none" or a
    different algorithm are rejected.
    """
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "iat", "sub"]},
        )
        return uuid.UUID(payload["sub"])
    except jwt.ExpiredSignatureError:
        raise AuthenticationError("Token has expired") from None
    except (jwt.InvalidTokenError, ValueError, TypeError):
        raise AuthenticationError("Invalid authentication token") from None
