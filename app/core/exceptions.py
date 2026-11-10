from app.core.constants import RESOURCE_CONFLICT, TASK_NOT_FOUND


class DomainException(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class NotFoundException(DomainException):
    def __init__(self, message: str = TASK_NOT_FOUND) -> None:
        super().__init__(message)


class ConflictException(DomainException):
    def __init__(self, message: str = RESOURCE_CONFLICT) -> None:
        super().__init__(message)


class InvalidReferenceException(DomainException):
    pass
