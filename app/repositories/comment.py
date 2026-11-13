from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Comment
from app.repositories.access import AccessRepository
from app.repositories.base import BaseRepository


class CommentRepository(AccessRepository, BaseRepository[Comment]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Comment)
