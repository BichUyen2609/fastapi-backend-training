from datetime import UTC, datetime, timedelta

from fastapi.concurrency import run_in_threadpool
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.core.constants import (
    EMAIL_ALREADY_REGISTERED,
    INVALID_CREDENTIALS,
    INVALID_REFRESH_TOKEN,
    PASSWORD_MAX_LENGTH,
    SECONDS_PER_DAY,
    SECONDS_PER_MINUTE,
)
from app.core.exceptions import AuthenticationException, ConflictException
from app.core.security import (
    create_access_token,
    dummy_password_hash,
    generate_refresh_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.models.entities import User
from app.repositories.auth import RefreshTokenRepository, UserRepository
from app.schemas.auth import RegisterRequest, TokenResponse
from app.services.base import transaction


class AuthService:
    def __init__(
        self,
        repository: UserRepository,
        tokens: RefreshTokenRepository,
        settings: Settings,
    ) -> None:
        self.repository = repository
        self.tokens = tokens
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

    async def issue_tokens(self, user_id: int) -> TokenResponse:
        refresh_token = generate_refresh_token()
        lifetime = self.settings.refresh_token_expire_days * SECONDS_PER_DAY
        await self.tokens.create(
            {
                "user_id": user_id,
                "token_hash": hash_token(refresh_token),
                "expires_at": datetime.now(UTC) + timedelta(seconds=lifetime),
            }
        )
        return TokenResponse(
            access_token=create_access_token(user_id, self.settings),
            refresh_token=refresh_token,
            expires_in=self.settings.access_token_expire_minutes * SECONDS_PER_MINUTE,
            refresh_expires_in=lifetime,
        )

    async def login(self, email: str, password: str) -> TokenResponse:
        if len(password) > PASSWORD_MAX_LENGTH:
            raise AuthenticationException(INVALID_CREDENTIALS)
        async with transaction(self.repository.session):
            user = await self.repository.get_by_email(email.strip().lower())
            hashed = user.hashed_password if user is not None else dummy_password_hash
            valid = await run_in_threadpool(verify_password, password, hashed)
            if user is None or not valid or not user.is_active:
                raise AuthenticationException(INVALID_CREDENTIALS)
            return await self.issue_tokens(user.id)

    async def refresh(self, refresh_token: str) -> TokenResponse:
        now = datetime.now(UTC)
        reused = False
        async with transaction(self.repository.session):
            stored = await self.tokens.get_by_hash(hash_token(refresh_token))
            if stored is None or stored.expires_at <= now:
                raise AuthenticationException(INVALID_REFRESH_TOKEN)
            if await self.tokens.revoke(stored.id, now):
                user = await self.repository.get(stored.user_id)
                if user is None or not user.is_active:
                    raise AuthenticationException(INVALID_REFRESH_TOKEN)
                tokens = await self.issue_tokens(user.id)
            else:
                await self.tokens.revoke_all(stored.user_id, now)
                reused = True
        if reused:
            raise AuthenticationException(INVALID_REFRESH_TOKEN)
        return tokens

    async def logout(self, refresh_token: str) -> None:
        async with transaction(self.repository.session):
            stored = await self.tokens.get_by_hash(hash_token(refresh_token))
            if stored is not None:
                await self.tokens.revoke(stored.id, datetime.now(UTC))
