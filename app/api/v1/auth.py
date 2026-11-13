from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.dependencies import AuthServiceDependency
from app.api.params import error_responses
from app.models.entities import User
from app.schemas.auth import (
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


def disable_cache(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(status.HTTP_409_CONFLICT),
)
async def register(data: RegisterRequest, service: AuthServiceDependency) -> User:
    return await service.register(data)


@router.post(
    "/login",
    response_model=TokenResponse,
    responses=error_responses(status.HTTP_401_UNAUTHORIZED),
)
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    service: AuthServiceDependency,
    response: Response,
) -> TokenResponse:
    disable_cache(response)
    return await service.login(form.username, form.password)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    responses=error_responses(status.HTTP_401_UNAUTHORIZED),
)
async def refresh(
    data: RefreshRequest, service: AuthServiceDependency, response: Response
) -> TokenResponse:
    disable_cache(response)
    return await service.refresh(data.refresh_token.get_secret_value())


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def logout(data: RefreshRequest, service: AuthServiceDependency) -> Response:
    await service.logout(data.refresh_token.get_secret_value())
    return Response(status_code=status.HTTP_204_NO_CONTENT)
