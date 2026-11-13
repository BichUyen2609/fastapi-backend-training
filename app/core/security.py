from datetime import UTC, datetime, timedelta
from hashlib import sha256
from secrets import token_urlsafe
from typing import Annotated, Literal
from uuid import uuid4

import jwt
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.config import Settings
from app.core.constants import (
    JWT_ALGORITHM,
    MAX_ENTITY_ID,
    REFRESH_TOKEN_BYTES,
    SECONDS_PER_MINUTE,
)
from app.core.exceptions import AuthenticationException

password_hasher = PasswordHash.recommended()
dummy_password_hash = password_hasher.hash(token_urlsafe(32))


class AccessClaims(BaseModel):
    model_config = ConfigDict(strict=True)

    sub: Annotated[str, Field(pattern=r"^[1-9][0-9]*$", max_length=10)]
    token_type: Literal["access"]
    jti: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
    exp: int
    iat: int
    nbf: int
    iss: str
    aud: str


def create_access_token(user_id: int, settings: Settings) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "token_type": "access",
        "jti": uuid4().hex,
        "iat": now,
        "nbf": now,
        "exp": now
        + timedelta(seconds=settings.access_token_expire_minutes * SECONDS_PER_MINUTE),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
    }
    return jwt.encode(payload, settings.signing_key(), algorithm=JWT_ALGORITHM)


def decode_access_token(token: str, settings: Settings) -> int:
    try:
        payload = jwt.decode(
            token,
            settings.signing_key(),
            algorithms=[JWT_ALGORITHM],
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            options={
                "require": [
                    "sub",
                    "exp",
                    "iat",
                    "nbf",
                    "iss",
                    "aud",
                    "jti",
                    "token_type",
                ]
            },
        )
        claims = AccessClaims.model_validate(payload)
        user_id = int(claims.sub)
        if user_id > MAX_ENTITY_ID:
            raise AuthenticationException()
        return user_id
    except (InvalidTokenError, ValidationError) as exc:
        raise AuthenticationException() from exc


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    try:
        return password_hasher.verify(password, hashed_password)
    except UnknownHashError:
        return False


def generate_refresh_token() -> str:
    return token_urlsafe(REFRESH_TOKEN_BYTES)


def hash_token(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()
