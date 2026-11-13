from typing import Annotated

from fastapi import Query, status

from app.core.constants import MAX_ENTITY_ID, MAX_LIMIT
from app.schemas.base import ErrorResponse

PageNumber = Annotated[int, Query(ge=1, le=MAX_ENTITY_ID)]
PageLimit = Annotated[int, Query(ge=1, le=MAX_LIMIT)]

ERROR_DESCRIPTIONS: dict[int, str] = {
    status.HTTP_400_BAD_REQUEST: "Request rejected by business rules",
    status.HTTP_401_UNAUTHORIZED: "Missing, invalid or expired credentials",
    status.HTTP_403_FORBIDDEN: "Insufficient permissions",
    status.HTTP_404_NOT_FOUND: "Resource not found",
    status.HTTP_409_CONFLICT: "Data conflict",
    status.HTTP_422_UNPROCESSABLE_CONTENT: "Invalid input or reference",
}


def error_responses(*codes: int) -> dict[int | str, dict[str, object]]:
    return {
        code: {"model": ErrorResponse, "description": ERROR_DESCRIPTIONS[code]}
        for code in codes
    }


RESOURCE_ERRORS = error_responses(
    status.HTTP_404_NOT_FOUND,
    status.HTTP_409_CONFLICT,
    status.HTTP_422_UNPROCESSABLE_CONTENT,
)
PROTECTED_ERRORS = error_responses(
    status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN
)
