from typing import Final

APP_NAME: Final = "TaskHub"
APP_VERSION: Final = "0.1.0"
API_V1_PREFIX: Final = "/api/v1"

TITLE_MIN_LENGTH: Final = 1
TITLE_MAX_LENGTH: Final = 200
DESCRIPTION_MAX_LENGTH: Final = 5_000
NAME_MAX_LENGTH: Final = 150
EMAIL_MAX_LENGTH: Final = 254
PASSWORD_HASH_MAX_LENGTH: Final = 255
COLOR_MAX_LENGTH: Final = 7
COMMENT_MAX_LENGTH: Final = 4_000
DEFAULT_PAGE: Final = 1
DEFAULT_LIMIT: Final = 20
MAX_LIMIT: Final = 100

TASK_NOT_FOUND: Final = "Task not found"
NON_NULL_FIELD_MESSAGE: Final = (
    "Field cannot be null; omit it to keep its current value"
)
