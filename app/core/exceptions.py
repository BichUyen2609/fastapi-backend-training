from app.core.constants import TASK_NOT_FOUND


class NotFoundException(Exception):
    """A requested domain resource does not exist."""

    def __init__(self, message: str = TASK_NOT_FOUND) -> None:
        self.message = message
        super().__init__(message)
