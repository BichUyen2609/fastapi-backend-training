from typing import Final

APP_NAME: Final = "TaskHub"
APP_VERSION: Final = "0.1.0"
API_V1_PREFIX: Final = "/api/v1"

TITLE_MIN_LENGTH: Final = 1
TITLE_MAX_LENGTH: Final = 200
DESCRIPTION_MAX_LENGTH: Final = 5_000

TASK_NOT_FOUND: Final = "Task not found"
NON_NULL_FIELD_MESSAGE: Final = (
    "Field cannot be null; omit it to keep its current value"
)
