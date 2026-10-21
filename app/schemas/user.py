import uuid
from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field, StringConstraints

from app.schemas.common import NO_NUL

LowerEmail = Annotated[EmailStr, AfterValidator(str.lower)]
FullName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120, pattern=NO_NUL)
]


class UserCreate(BaseModel):
    email: LowerEmail
    password: str = Field(min_length=8, max_length=128)
    full_name: FullName


class LoginRequest(BaseModel):
    email: LowerEmail
    # max_length bounds the work Argon2 does on attacker-supplied input.
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Seconds until the token expires")


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    is_active: bool
    created_at: datetime
