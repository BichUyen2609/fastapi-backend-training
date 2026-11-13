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
from pydantic.json_schema import SkipJsonSchema

from app.core.constants import (
    EMAIL_MAX_LENGTH,
    NAME_MAX_LENGTH,
    PASSWORD_MAX_LENGTH,
    PASSWORD_MIN_LENGTH,
    REFRESH_TOKEN_MAX_LENGTH,
)
from app.core.enums import UserRole
from app.schemas.base import BaseSchema, ResourceId, reject_null

Email = Annotated[EmailStr, Field(max_length=EMAIL_MAX_LENGTH)]
FullName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=NAME_MAX_LENGTH),
]
Password = Annotated[
    SecretStr, Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)
]


def normalize_email(value: object) -> object:
    return value.strip().lower() if isinstance(value, str) else value


class RegisterRequest(BaseSchema):
    model_config = ConfigDict(str_strip_whitespace=False)

    email: Email
    full_name: FullName
    password: Password

    _normalize_email = field_validator("email", mode="before")(normalize_email)


class UserUpdate(BaseSchema):
    email: Email | SkipJsonSchema[None] = None
    full_name: FullName | SkipJsonSchema[None] = None

    _normalize_email = field_validator("email", mode="before")(normalize_email)
    _reject_null = field_validator("email", "full_name", mode="before")(reject_null)


class PasswordChange(BaseSchema):
    model_config = ConfigDict(str_strip_whitespace=False)

    current_password: Annotated[
        SecretStr, Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)
    ]
    new_password: Password


class RefreshRequest(BaseSchema):
    refresh_token: Annotated[
        SecretStr, Field(min_length=1, max_length=REFRESH_TOKEN_MAX_LENGTH)
    ]


class UserResponse(BaseSchema):
    id: ResourceId
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    created_at: AwareDatetime


class TokenResponse(BaseSchema):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    refresh_expires_in: int
