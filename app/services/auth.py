from fastapi.concurrency import run_in_threadpool
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.core.constants import (
    EMAIL_ALREADY_REGISTERED,
    INVALID_CREDENTIALS,
    PASSWORD_MAX_LENGTH,
    SECONDS_PER_MINUTE,
)
from app.core.exceptions import AuthenticationException, ConflictException
from app.core.security import (
    create_access_token,
    dummy_password_hash,
    hash_password,
    verify_password,
)
from app.models.entities import User
from app.repositories.auth import UserRepository
from app.schemas.auth import RegisterRequest, TokenResponse


class AuthService:
    def __init__(self, repository: UserRepository, settings: Settings) -> None:
        self.repository = repository
        self.settings = settings

    async def register(self, data: RegisterRequest) -> User:
        hashed = await run_in_threadpool(
            hash_password, data.password.get_secret_value()
        )
        try:
            async with self.repository.session.begin():
                if await self.repository.get_by_email(str(data.email)) is not None:
                    raise ConflictException(EMAIL_ALREADY_REGISTERED)
                user = await self.repository.create(
                    {
                        "email": str(data.email),
                        "full_name": data.full_name,
                        "hashed_password": hashed,
                    }
                )
        except IntegrityError as exc:
            raise ConflictException(EMAIL_ALREADY_REGISTERED) from exc
        await self.repository.session.refresh(user)
        return user

    async def login(self, email: str, password: str) -> TokenResponse:
        if len(password) > PASSWORD_MAX_LENGTH:
            raise AuthenticationException(INVALID_CREDENTIALS)
        user = await self.repository.get_by_email(email.strip().lower())
        hashed = user.hashed_password if user is not None else dummy_password_hash
        valid = await run_in_threadpool(verify_password, password, hashed)
        if user is None or not valid or not user.is_active:
            raise AuthenticationException(INVALID_CREDENTIALS)
        return TokenResponse(
            access_token=create_access_token(user.id, self.settings),
            expires_in=self.settings.access_token_expire_minutes * SECONDS_PER_MINUTE,
        )
