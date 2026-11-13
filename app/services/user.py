from datetime import UTC, datetime

from fastapi.concurrency import run_in_threadpool

from app.core.constants import (
    EMAIL_ALREADY_REGISTERED,
    INCORRECT_PASSWORD,
    PASSWORD_UNCHANGED,
    USER_NOT_FOUND,
)
from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    NotFoundException,
)
from app.core.security import hash_password, verify_password
from app.models.entities import User
from app.repositories.auth import RefreshTokenRepository, UserRepository
from app.schemas.auth import PasswordChange, UserUpdate
from app.services.base import transaction


class UserService:
    def __init__(
        self,
        repository: UserRepository,
        tokens: RefreshTokenRepository,
        actor: User,
    ) -> None:
        self.repository = repository
        self.tokens = tokens
        self.actor = actor

    async def update_profile(self, data: UserUpdate) -> User:
        changes = data.model_dump(exclude_unset=True)
        if "email" in changes:
            changes["email"] = str(changes["email"])
        async with transaction(self.repository.session, EMAIL_ALREADY_REGISTERED):
            if changes.get("email") not in (None, self.actor.email):
                existing = await self.repository.get_by_email(changes["email"])
                if existing is not None and existing.id != self.actor.id:
                    raise ConflictException(EMAIL_ALREADY_REGISTERED)
            if changes:
                user = await self.repository.update(self.actor.id, changes)
                if user is None:
                    raise NotFoundException(USER_NOT_FOUND)
                self.actor = user
        return self.actor

    async def change_password(self, data: PasswordChange) -> None:
        current = data.current_password.get_secret_value()
        new = data.new_password.get_secret_value()
        if not await run_in_threadpool(
            verify_password, current, self.actor.hashed_password
        ):
            raise BadRequestException(INCORRECT_PASSWORD)
        if current == new:
            raise BadRequestException(PASSWORD_UNCHANGED)
        hashed = await run_in_threadpool(hash_password, new)
        async with transaction(self.repository.session):
            await self.repository.update(self.actor.id, {"hashed_password": hashed})
            await self.tokens.revoke_all(self.actor.id, datetime.now(UTC))
