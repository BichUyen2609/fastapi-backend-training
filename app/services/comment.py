from app.core.constants import COMMENT_NOT_FOUND, PROJECT_ARCHIVED, TASK_NOT_FOUND
from app.core.enums import ProjectStatus, WorkspaceRole
from app.core.exceptions import ConflictException, NotFoundException
from app.models.entities import Comment, User
from app.repositories.comment import CommentRepository
from app.schemas.comment import CommentCreate, CommentPage, CommentResponse
from app.services.base import authorize_project, ensure_role, transaction


class CommentService:
    def __init__(self, repository: CommentRepository, actor: User) -> None:
        self.repository = repository
        self.actor = actor

    async def task_project(self, task_id: int) -> int:
        project_id = await self.repository.task_project(task_id)
        if project_id is None:
            raise NotFoundException(TASK_NOT_FOUND)
        return project_id

    async def list_comments(self, task_id: int, page: int, limit: int) -> CommentPage:
        await authorize_project(
            self.repository, self.actor, await self.task_project(task_id)
        )
        items, total = await self.repository.paginate(
            page, limit, (Comment.task_id == task_id,)
        )
        return CommentPage(
            items=[CommentResponse.model_validate(item) for item in items],
            total=total,
            page=page,
            limit=limit,
        )

    async def add_comment(self, task_id: int, data: CommentCreate) -> Comment:
        async with transaction(self.repository.session):
            project_id = await self.task_project(task_id)
            await authorize_project(self.repository, self.actor, project_id, write=True)
            comment = await self.repository.create(
                data.model_dump() | {"task_id": task_id, "author_id": self.actor.id}
            )
        await self.repository.session.refresh(comment)
        return comment

    async def delete_comment(self, comment_id: int) -> None:
        async with transaction(self.repository.session):
            comment = await self.repository.get(comment_id)
            if comment is None:
                raise NotFoundException(COMMENT_NOT_FOUND)
            access = await self.repository.project_access(
                await self.task_project(comment.task_id), self.actor.id
            )
            if access is None:
                raise NotFoundException(COMMENT_NOT_FOUND)
            ensure_role(
                self.actor,
                access.role,
                WorkspaceRole.VIEWER
                if comment.author_id == self.actor.id
                else WorkspaceRole.OWNER,
            )
            if access.status == ProjectStatus.ARCHIVED:
                raise ConflictException(PROJECT_ARCHIVED)
            await self.repository.delete(comment_id)
