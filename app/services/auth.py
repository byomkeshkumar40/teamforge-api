from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AuthenticationError, ConflictError, PermissionDeniedError
from app.core.security import dummy_hash, hash_password, verify_password
from app.models import User
from app.schemas.user import UserCreate

EMAIL_TAKEN = "An account with this email already exists"


def register_user(db: Session, data: UserCreate) -> User:
    if db.scalar(select(User.id).where(User.email == data.email)):
        raise ConflictError(EMAIL_TAKEN)
    user = User(
        email=data.email,
        password_hash=hash_password(data.password),
        full_name=data.full_name,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        # Two simultaneous registrations passed the check above; the unique index decides.
        db.rollback()
        raise ConflictError(EMAIL_TAKEN) from None
    return user


def authenticate(db: Session, email: str, password: str) -> User:
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        verify_password(password, dummy_hash())  # equalise timing with the real-user path
        raise AuthenticationError("Incorrect email or password")
    if not verify_password(password, user.password_hash):
        raise AuthenticationError("Incorrect email or password")
    if not user.is_active:
        # Only revealed after the correct password was supplied.
        raise PermissionDeniedError("This account is disabled")
    return user
