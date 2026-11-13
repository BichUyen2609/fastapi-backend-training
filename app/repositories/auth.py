from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import RefreshToken, User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, User)

    async def get_by_email(self, email: str) -> User | None:
        result = await self.session.scalar(
            select(User).where(func.lower(User.email) == email.lower())
        )
        return result


class RefreshTokenRepository(BaseRepository[RefreshToken]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, RefreshToken)

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        result = await self.session.scalars(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        return result.one_or_none()

    async def revoke(self, token_id: int, revoked_at: datetime) -> bool:
        statement = (
            update(RefreshToken)
            .where(RefreshToken.id == token_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=revoked_at)
            .returning(RefreshToken.id)
        )
        return (await self.session.execute(statement)).scalar_one_or_none() is not None

    async def revoke_all(self, user_id: int, revoked_at: datetime) -> None:
        await self.session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=revoked_at)
        )
