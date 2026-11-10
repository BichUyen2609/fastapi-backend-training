from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.dependencies import AuthServiceDependency, CurrentUser
from app.models.entities import User
from app.schemas.auth import RegisterRequest, TokenResponse, UserResponse
from app.schemas.base import ErrorResponse

router = APIRouter(tags=["Authentication"])


@router.post(
    "/auth/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_409_CONFLICT: {"model": ErrorResponse}},
)
async def register(data: RegisterRequest, service: AuthServiceDependency) -> User:
    return await service.register(data)


@router.post(
    "/auth/login",
    response_model=TokenResponse,
    responses={status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse}},
)
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    service: AuthServiceDependency,
    response: Response,
) -> TokenResponse:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return await service.login(form.username, form.password)


@router.get(
    "/users/me",
    response_model=UserResponse,
    responses={status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse}},
)
async def get_profile(user: CurrentUser) -> User:
    return user
