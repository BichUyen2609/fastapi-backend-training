from fastapi import APIRouter, Response, status

from app.api.dependencies import CurrentUser, UserServiceDependency
from app.api.params import error_responses
from app.models.entities import User
from app.schemas.auth import PasswordChange, UserResponse, UserUpdate

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("/me", response_model=UserResponse)
async def get_profile(user: CurrentUser) -> User:
    return user


@router.patch(
    "/me",
    response_model=UserResponse,
    responses=error_responses(
        status.HTTP_409_CONFLICT, status.HTTP_422_UNPROCESSABLE_CONTENT
    ),
)
async def update_profile(data: UserUpdate, service: UserServiceDependency) -> User:
    return await service.update_profile(data)


@router.post(
    "/me/password",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=error_responses(
        status.HTTP_400_BAD_REQUEST, status.HTTP_422_UNPROCESSABLE_CONTENT
    ),
)
async def change_password(
    data: PasswordChange, service: UserServiceDependency
) -> Response:
    await service.change_password(data)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
