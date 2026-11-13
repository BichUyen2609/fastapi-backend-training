from fastapi import APIRouter, Response, status

from app.api.dependencies import CommentServiceDependency
from app.api.params import RESOURCE_ERRORS, PageLimit, PageNumber
from app.core.constants import DEFAULT_LIMIT, DEFAULT_PAGE
from app.models.entities import Comment
from app.schemas.base import ResourceId
from app.schemas.comment import CommentCreate, CommentPage, CommentResponse

router = APIRouter(tags=["Comments"], responses=RESOURCE_ERRORS)


@router.post(
    "/tasks/{task_id}/comments",
    response_model=CommentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_comment(
    task_id: ResourceId, data: CommentCreate, service: CommentServiceDependency
) -> Comment:
    return await service.add_comment(task_id, data)


@router.get("/tasks/{task_id}/comments", response_model=CommentPage)
async def list_comments(
    task_id: ResourceId,
    service: CommentServiceDependency,
    page: PageNumber = DEFAULT_PAGE,
    limit: PageLimit = DEFAULT_LIMIT,
) -> CommentPage:
    return await service.list_comments(task_id, page, limit)


@router.delete(
    "/comments/{comment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_comment(
    comment_id: ResourceId, service: CommentServiceDependency
) -> Response:
    await service.delete_comment(comment_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
