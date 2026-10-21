from fastapi import APIRouter, status

from app.api.deps import CurrentUser, DbSession
from app.core.config import get_settings
from app.core.security import create_access_token
from app.schemas.user import LoginRequest, TokenResponse, UserCreate, UserRead
from app.services import auth as auth_service

router = APIRouter(tags=["auth"])


@router.post("/auth/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(data: UserCreate, db: DbSession):
    return auth_service.register_user(db, data)


@router.post("/auth/login", response_model=TokenResponse)
def login(data: LoginRequest, db: DbSession):
    user = auth_service.authenticate(db, data.email, data.password)
    minutes = get_settings().access_token_expire_minutes
    return TokenResponse(access_token=create_access_token(user.id), expires_in=minutes * 60)


@router.get("/users/me", response_model=UserRead)
def read_current_user(current_user: CurrentUser):
    return current_user
