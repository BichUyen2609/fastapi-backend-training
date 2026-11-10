from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    ConfigDict,
    EmailStr,
    Field,
    SecretStr,
    StringConstraints,
    field_validator,
)

from app.core.constants import (
    EMAIL_MAX_LENGTH,
    NAME_MAX_LENGTH,
    PASSWORD_MAX_LENGTH,
    PASSWORD_MIN_LENGTH,
)
from app.core.enums import UserRole
from app.schemas.base import BaseSchema, ResourceId


class RegisterRequest(BaseSchema):
    model_config = ConfigDict(str_strip_whitespace=False)

    email: Annotated[EmailStr, Field(max_length=EMAIL_MAX_LENGTH)]
    full_name: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=1, max_length=NAME_MAX_LENGTH
        ),
    ]
    password: Annotated[
        SecretStr, Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)
    ]

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value


class UserResponse(BaseSchema):
    id: ResourceId
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    created_at: AwareDatetime


class TokenResponse(BaseSchema):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
