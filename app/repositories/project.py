from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Project
from app.repositories.access import AccessRepository
from app.repositories.base import BaseRepository


class ProjectRepository(AccessRepository, BaseRepository[Project]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Project)
