import asyncio
import logging

from sqlalchemy import select

from app.core.config import get_settings
from app.core.enums import WorkspaceRole
from app.core.security import hash_password
from app.database import Database
from app.models.entities import Project, User, Workspace, WorkspaceMember

logger = logging.getLogger(__name__)


async def seed() -> None:
    settings = get_settings()
    if settings.demo_email is None or settings.demo_password is None:
        raise RuntimeError("Set DEMO_EMAIL and DEMO_PASSWORD before seeding")
    database = Database(settings)
    try:
        async with database.sessions() as session:
            async with session.begin():
                user = await session.scalar(
                    select(User).where(User.email == settings.demo_email)
                )
                if user is not None:
                    project = await session.scalar(
                        select(Project)
                        .join(Workspace)
                        .where(Workspace.owner_id == user.id)
                    )
                    if project is not None:
                        logger.info(
                            "Demo user_id=%s project_id=%s", user.id, project.id
                        )
                        return
                else:
                    user = User(
                        email=settings.demo_email,
                        full_name="Demo User",
                        hashed_password=hash_password(
                            settings.demo_password.get_secret_value()
                        ),
                    )
                    session.add(user)
                    await session.flush()
                workspace = Workspace(name="Demo Workspace", owner_id=user.id)
                session.add(workspace)
                await session.flush()
                session.add(
                    WorkspaceMember(
                        workspace_id=workspace.id,
                        user_id=user.id,
                        role=WorkspaceRole.OWNER,
                    )
                )
                project = Project(name="Demo Project", workspace_id=workspace.id)
                session.add(project)
                await session.flush()
            await session.refresh(project)
            logger.info("Demo user_id=%s project_id=%s", user.id, project.id)
    finally:
        await database.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(seed())
