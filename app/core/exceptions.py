from typing import ClassVar

from app.core.constants import (
    AUTHENTICATION_REQUIRED,
    INSUFFICIENT_PERMISSIONS,
    RESOURCE_CONFLICT,
    TASK_NOT_FOUND,
)


class DomainException(Exception):
    status_code: ClassVar[int] = 400
    code: ClassVar[str] = "BAD_REQUEST"

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class BadRequestException(DomainException):
    pass


class NotFoundException(DomainException):
    status_code = 404
    code = "NOT_FOUND"

    def __init__(self, message: str = TASK_NOT_FOUND) -> None:
        super().__init__(message)


class ConflictException(DomainException):
    status_code = 409
    code = "CONFLICT"

    def __init__(self, message: str = RESOURCE_CONFLICT) -> None:
        super().__init__(message)


class InvalidReferenceException(DomainException):
    status_code = 422
    code = "INVALID_REFERENCE"


class AuthenticationException(DomainException):
    status_code = 401
    code = "UNAUTHORIZED"

    def __init__(self, message: str = AUTHENTICATION_REQUIRED) -> None:
        super().__init__(message)


class ForbiddenException(DomainException):
    status_code = 403
    code = "FORBIDDEN"

    def __init__(self, message: str = INSUFFICIENT_PERMISSIONS) -> None:
        super().__init__(message)
